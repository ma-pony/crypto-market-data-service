# 智能缺口检测算法

## 概述

智能缺口检测算法能够精确识别时间序列数据中任意位置的缺失记录，而不仅仅是开始或结束位置的缺失。

## 算法流程

### 1. 计算目标时间范围

```python
current_time_ms = int(time.time() * 1000)
target_start_ms = current_time_ms - (gap_days * 24 * 60 * 60 * 1000)
```

例如: 如果 `gap_days=90`，则检查最近90天的数据。

### 2. 生成预期时间点集合

```python
# 对齐到时间周期边界
aligned_start = (target_start_ms // timeframe_ms) * timeframe_ms

# 生成所有应该存在的时间点
expected_timestamps = set()
current = aligned_start
while current <= current_time_ms:
    expected_timestamps.add(current)
    current += timeframe_ms
```

对于1日线（timeframe_ms = 86400000）:
- 2025-01-01 00:00:00
- 2025-01-02 00:00:00
- 2025-01-03 00:00:00
- ...
- 2025-03-31 00:00:00

### 3. 查询实际存在的时间点

```python
stmt = (
    select(OHLCV.timestamp)
    .where(
        OHLCV.exchange == exchange,
        OHLCV.symbol == symbol,
        OHLCV.timeframe == timeframe,
        OHLCV.timestamp >= target_start_ms,
    )
    .order_by(OHLCV.timestamp)
)
existing_timestamps = set(row[0] for row in result.all())
```

### 4. 计算缺失时间点

```python
missing_timestamps = sorted(expected_timestamps - existing_timestamps)
```

集合差运算找出所有缺失的时间点。

### 5. 分组连续缺口

```python
gaps = []
if missing_timestamps:
    gap_start = missing_timestamps[0]
    gap_end = missing_timestamps[0]
    
    for ts in missing_timestamps[1:]:
        if ts == gap_end + timeframe_ms:
            # 连续的时间点，扩展当前区间
            gap_end = ts
        else:
            # 不连续，保存当前区间并开始新区间
            gaps.append((gap_start, gap_end))
            gap_start = ts
            gap_end = ts
    
    gaps.append((gap_start, gap_end))
```

### 6. 批量补全每个缺口

```python
for gap_start, gap_end in gaps:
    gap_size = int((gap_end - gap_start) / timeframe_ms) + 1
    
    # 分批获取数据（每次最多1000条）
    batch_size = 1000
    current_start = gap_start
    
    while current_start <= gap_end:
        remaining = int((gap_end - current_start) / timeframe_ms) + 1
        limit = min(batch_size, remaining)
        
        records = await client.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            since=current_start,
            limit=limit,
        )
        
        await ohlcv_repo.save(session, records)
        current_start = records[-1].timestamp + timeframe_ms
        
        # 避免API限制
        await asyncio.sleep(1.0)
```

## 示例场景

### 场景1: 中间缺失

假设90天范围内的数据状态:
```
第1-30天:  ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓ (30条)
第31-35天: ✗✗✗✗✗ (缺失5条)
第36-80天: ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓ (45条)
第81天:    ✗ (缺失1条)
第82-90天: ✓✓✓✓✓✓✓✓✓ (9条)
```

算法输出:
```
gap_fill_detected:
  missing_count=6
  expected_count=90
  coverage_pct=93.3%

gap_fill_plan:
  gap_count=2
  total_missing=6

Gap 1: 第31天 to 第35天 (5 records)
Gap 2: 第81天 to 第81天 (1 record)
```

### 场景2: 完全连续

假设90天范围内的数据状态:
```
第1-90天: ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓... (90条)
```

算法输出:
```
gap_fill_not_needed:
  checked_range_days=90
```

### 场景3: 多个小缺口

假设90天范围内的数据状态:
```
第1-10天:  ✓✓✓✓✓✓✓✓✓✓ (10条)
第11天:    ✗ (缺失1条)
第12-20天: ✓✓✓✓✓✓✓✓✓ (9条)
第21天:    ✗ (缺失1条)
第22-30天: ✓✓✓✓✓✓✓✓✓ (9条)
第31天:    ✗ (缺失1条)
第32-90天: ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓... (59条)
```

算法输出:
```
gap_fill_detected:
  missing_count=3
  expected_count=90
  coverage_pct=96.7%

gap_fill_plan:
  gap_count=3
  total_missing=3

Gap 1: 第11天 to 第11天 (1 record)
Gap 2: 第21天 to 第21天 (1 record)
Gap 3: 第31天 to 第31天 (1 record)
```

## 优势

1. **精确检测**: 能发现任意位置的缺失，不仅仅是边界
2. **避免重复**: 只补全真正缺失的数据
3. **优化请求**: 连续缺口合并为一次API调用
4. **覆盖率统计**: 提供补全前后的数据完整性指标
5. **灵活配置**: 支持1-365天的检查范围

## 性能考虑

### 时间复杂度
- 生成预期时间点: O(n)，n = gap_days
- 查询数据库: O(n log n)，数据库索引查询
- 集合差运算: O(n)
- 分组缺口: O(m)，m = missing_count
- 总体: O(n log n)

### 空间复杂度
- 预期时间点集合: O(n)
- 实际时间点集合: O(n)
- 缺失时间点列表: O(m)
- 总体: O(n)

对于90天的1日线数据，n=90，内存占用可忽略不计。

### 数据库优化
- 在 `(exchange, symbol, timeframe, timestamp)` 上建立索引
- 使用 `timestamp >= target_start_ms` 过滤，利用索引
- 只查询 timestamp 字段，减少数据传输

## API频率控制

```python
# 每批次之间延迟1秒
await asyncio.sleep(1.0)

# 遇到rate limit自动暂停
except RateLimitError as e:
    self._pause_exchange(exchange, e.retry_after)
```

这确保了即使补全大量数据也不会触发交易所API限制。

## 日志示例

### 检测到缺口
```json
{
  "event": "gap_fill_detected",
  "exchange": "binance",
  "symbol": "BTC/USDT",
  "timeframe": "1d",
  "missing_count": 6,
  "expected_count": 90,
  "coverage_pct": "93.3%",
  "gap_days": 90
}
```

### 补全计划
```json
{
  "event": "gap_fill_plan",
  "exchange": "binance",
  "symbol": "BTC/USDT",
  "timeframe": "1d",
  "gap_count": 2,
  "total_missing": 6
}
```

### 补全完成
```json
{
  "event": "gap_filled",
  "exchange": "binance",
  "symbol": "BTC/USDT",
  "timeframe": "1d",
  "records_filled": 6,
  "coverage_before": "93.3%",
  "coverage_after": "100.0%"
}
```

### 无需补全
```json
{
  "event": "gap_fill_not_needed",
  "exchange": "binance",
  "symbol": "BTC/USDT",
  "timeframe": "1d",
  "checked_range_days": 90
}
```

## 使用建议

1. **不需要频繁执行**: 智能检测确保只补全缺失部分，每天或每周执行一次即可
2. **服务稳定时无需手动**: 定时采集任务会自动收集新数据
3. **适合的场景**:
   - 服务长时间停机后重启
   - 发现数据采集失败
   - 定期维护检查
   - 新增交易所或交易对

4. **配置建议**:
   - 日常检查: `gap_days=30`
   - 深度检查: `gap_days=90` 或 `gap_days=365`
   - API限制严格的交易所: 增加延迟时间
