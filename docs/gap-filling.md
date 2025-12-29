# Gap Filling (数据补全) 功能说明

## 概述

Gap Filling 是一个自动历史数据补全功能，用于在以下场景中自动补全缺失的 OHLCV 数据：

- 服务首次启动时，自动拉取历史数据
- 服务因异常停止后重启，自动补全停机期间的数据
- 数据采集失败后恢复，自动补全缺失的时间段

## 工作原理

### 1. 启动时触发

当服务启动时，调度器会为每个 `(exchange, symbol, timeframe)` 组合异步执行一次 gap filling：

```python
# 在 scheduler.start() 中
if gap_fill_enabled:
    asyncio.create_task(
        self._fill_ohlcv_gap(ex.id, symbol, tf, gap_fill_days)
    )
```

### 2. 检测数据缺口

Gap filling 逻辑会：

1. 查询数据库中该组合的最新记录
2. 计算最新记录时间与当前时间的差距
3. 如果差距大于一个时间周期，则认为存在缺口

```python
# 示例：1h 周期
timeframe_ms = 3600 * 1000  # 1 小时 = 3600000 毫秒
gap_ms = current_time - latest_record_time

if gap_ms < timeframe_ms:
    # 缺口小于一个周期，不需要补全
    return
```

### 3. 补全历史数据

如果检测到缺口，系统会：

1. 从最新记录时间开始，向前补全数据
2. 如果没有历史记录，从 `gap_fill_days` 天前开始补全
3. 分批获取数据（每批最多 1000 条）
4. 使用 upsert 机制，避免重复数据

```python
# 分批获取
while start_time < current_time:
    records = await client.fetch_ohlcv(
        symbol=symbol,
        timeframe=timeframe,
        since=start_time,
        limit=1000,
    )
    
    # 保存到数据库
    await ohlcv_repo.save(session, records)
    
    # 更新起始时间
    start_time = records[-1].timestamp + 1
```

## 配置参数

### 环境变量 (.env)

```bash
# 是否启用数据补全
GAP_FILL_ENABLED=true

# 补全多少天的历史数据（最大值）
GAP_FILL_DAYS=7
```

### YAML 配置 (config.yaml)

```yaml
# 数据补全配置
gap_fill_enabled: true
gap_fill_days: 7
```

## 使用场景

### 场景 1: 首次启动

**情况**: 数据库为空，首次启动服务

**行为**:
- 自动拉取最近 7 天的历史数据
- 为每个配置的 (exchange, symbol, timeframe) 组合补全数据

**日志示例**:
```
[info] gap_fill_initial exchange=binance symbol=BTC/USDT timeframe=1h days=7
[info] gap_filled exchange=binance symbol=BTC/USDT timeframe=1h records_filled=168
```

### 场景 2: 服务停机后重启

**情况**: 服务停机 2 小时后重启

**行为**:
- 检测到最新记录是 2 小时前
- 自动补全这 2 小时的数据

**日志示例**:
```
[info] gap_filled exchange=binance symbol=BTC/USDT timeframe=1h records_filled=2
```

### 场景 3: 数据采集失败

**情况**: 某个交易所因网络问题导致数据采集失败 30 分钟

**行为**:
- 下次正常采集时，检测到缺口
- 自动补全这 30 分钟的数据

### 场景 4: 长时间停机

**情况**: 服务停机 30 天后重启

**行为**:
- 检测到缺口为 30 天
- 受 `gap_fill_days=7` 限制，只补全最近 7 天的数据
- 避免一次性拉取过多数据

**日志示例**:
```
[warning] gap_fill_limited exchange=binance symbol=BTC/USDT timeframe=1h actual_gap_days=30 limited_to_days=7
[info] gap_filled exchange=binance symbol=BTC/USDT timeframe=1h records_filled=168
```

## 性能考虑

### 1. 异步执行

Gap filling 使用 `asyncio.create_task()` 异步执行，不会阻塞服务启动：

```python
# 不会阻塞
asyncio.create_task(self._fill_ohlcv_gap(...))

# 服务立即可用
self._scheduler.start()
```

### 2. 分批获取

每次最多获取 1000 条记录，避免单次请求过大：

```python
records = await client.fetch_ohlcv(
    symbol=symbol,
    timeframe=timeframe,
    since=start_time,
    limit=1000,  # 限制每批数量
)
```

### 3. Rate Limit 处理

如果触发交易所速率限制，会自动暂停该交易所的所有采集任务：

```python
except RateLimitError as e:
    self._pause_exchange(exchange, e.retry_after)
```

### 4. 请求间隔

批次之间有 0.5 秒的延迟，避免请求过快：

```python
await asyncio.sleep(0.5)
```

## 监控和日志

### 正常补全

```
[info] gap_filled exchange=binance symbol=BTC/USDT timeframe=1h records_filled=168
```

### 不需要补全

```
[debug] gap_fill_not_needed exchange=binance symbol=BTC/USDT timeframe=1h gap_ms=2421810
```

### 补全受限

```
[warning] gap_fill_limited exchange=binance symbol=BTC/USDT timeframe=1h actual_gap_days=30 limited_to_days=7
```

### 速率限制

```
[warning] gap_fill_rate_limited exchange=binance symbol=BTC/USDT timeframe=1h retry_after=60
```

### 补全失败

```
[error] gap_fill_failed exchange=binance symbol=BTC/USDT timeframe=1h error=... error_type=...
```

## 最佳实践

### 1. 合理设置补全天数

```bash
# 开发环境：快速启动
GAP_FILL_DAYS=1

# 生产环境：平衡数据完整性和启动速度
GAP_FILL_DAYS=7

# 数据分析：需要更多历史数据
GAP_FILL_DAYS=30
```

### 2. 监控补全进度

通过日志监控补全进度：

```bash
# 查看补全日志
grep "gap_fill" logs/app.log

# 统计补全的记录数
grep "gap_filled" logs/app.log | grep -oP "records_filled=\K\d+" | awk '{s+=$1} END {print s}'
```

### 3. 处理补全失败

如果补全失败，可以：

1. 检查网络连接
2. 检查交易所 API 状态
3. 增加 `gap_fill_days` 限制
4. 手动触发补全（重启服务）

## 手动触发补全

如果需要手动触发补全，可以重启服务：

```bash
# 停止服务
pkill -f "uvicorn src.main:app"

# 启动服务（会自动触发 gap filling）
uv run uvicorn src.main:app --reload
```

## 禁用 Gap Filling

如果不需要自动补全功能，可以禁用：

```bash
# .env
GAP_FILL_ENABLED=false
```

或

```yaml
# config.yaml
gap_fill_enabled: false
```

## 技术细节

### Upsert 机制

使用 PostgreSQL 的 `ON CONFLICT DO UPDATE` 实现幂等写入：

```python
stmt = insert(OHLCV).values([...])
stmt = stmt.on_conflict_do_update(
    constraint='uq_ohlcv_key',
    set_={
        'open': stmt.excluded.open,
        'high': stmt.excluded.high,
        'low': stmt.excluded.low,
        'close': stmt.excluded.close,
        'volume': stmt.excluded.volume,
    }
)
```

这确保：
- 重复数据会更新而不是插入
- 多次补全不会产生重复记录
- 可以安全地重试补全操作

### 缓存更新

补全的数据会同时更新到 Redis 缓存：

```python
await self.ohlcv_repo.save(session, records)
# 内部会调用
await self.cache.cache_ohlcv(records)
```

## 常见问题

### Q: 为什么启动时没有补全数据？

A: 可能的原因：
1. `GAP_FILL_ENABLED=false` 被禁用
2. 数据库中已有最新数据，不需要补全
3. 补全正在后台异步执行，查看日志确认

### Q: 补全会影响服务启动速度吗？

A: 不会。Gap filling 是异步执行的，不会阻塞服务启动。服务会立即可用，补全在后台进行。

### Q: 如果补全过程中服务重启会怎样？

A: 没有问题。下次启动时会重新检测缺口并补全。由于使用 upsert 机制，不会产生重复数据。

### Q: 可以补全超过 gap_fill_days 的数据吗？

A: 可以。增加 `GAP_FILL_DAYS` 配置即可。但要注意：
- 补全时间会更长
- 可能触发交易所速率限制
- 建议分多次补全，而不是一次性补全太多

### Q: Gap filling 会影响正常的数据采集吗？

A: 不会。Gap filling 和正常采集是独立的：
- Gap filling 只在启动时执行一次
- 正常采集按调度器定时执行
- 两者使用相同的 upsert 机制，不会冲突

## 总结

Gap Filling 功能提供了：

- ✅ **自动化**: 无需手动干预，自动检测和补全数据缺口
- ✅ **智能化**: 根据实际缺口大小决定是否补全
- ✅ **安全性**: 使用 upsert 机制，避免重复数据
- ✅ **高性能**: 异步执行，不阻塞服务启动
- ✅ **可配置**: 灵活的配置选项，适应不同场景
- ✅ **可监控**: 详细的日志输出，方便监控和排查问题

这确保了即使在服务异常停止或数据采集失败的情况下，也能保持数据的完整性和连续性。
