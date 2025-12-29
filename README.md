# Crypto Market Data Service

数字货币交易数据服务 - 为量化交易系统提供统一的市场数据访问能力。

## 功能特性

- 📊 **K线数据 (OHLCV)**: 支持多交易所、多交易对、多时间周期的历史K线数据查询
- 💹 **实时行情 (Ticker)**: 提供实时价格、24小时统计等市场快照数据
- 🚀 **高性能缓存**: Redis 双层缓存策略，OHLCV 使用 Sorted Set + 大小限制，Ticker 使用 TTL 自动过期
- 🔄 **自动采集**: 后台定时采集数据，Ticker 每 10 秒更新，OHLCV 按周期自动采集
- 📦 **批量查询**: 支持一次查询多个交易对，提高效率
- 🔍 **游标分页**: 大数据集查询支持游标分页，避免性能问题
- 🔗 **请求追踪**: 集成 Correlation ID，每个请求自动生成唯一标识，方便日志追踪和问题排查
- 🏥 **健康检查**: 实时监控 PostgreSQL、Redis 和交易所连接状态
- 🔧 **智能补全**: 智能检测并补全历史数据缺口，支持1-365天范围，避免重复拉取

## 技术栈

- **语言**: Python 3.11+
- **包管理**: uv
- **Web框架**: FastAPI
- **数据库**: PostgreSQL 15+ (异步连接池)
- **缓存**: Redis 7+ (双层缓存策略)
- **ORM**: SQLAlchemy 2.0 (异步)
- **交易所**: CCXT (支持 Binance, OKX, Gate.io 等)
- **调度**: APScheduler (后台数据采集)
- **日志**: structlog (结构化日志 + Correlation ID)
- **请求追踪**: asgi-correlation-id

## 架构设计

### 缓存策略

#### OHLCV 数据
- **存储结构**: Redis Sorted Set (按 timestamp 排序)
- **过期策略**: 大小限制 + 自动裁剪 (默认保留最新 1000 条)
- **内存占用**: 可预测且可控 (~27 MB 满载)
- **查询性能**: 支持高效的时间范围查询

#### Ticker 数据
- **存储结构**: Redis String + TTL
- **过期策略**: 自动过期 (默认 10 秒)
- **内存占用**: 极小 (~2 KB)
- **更新频率**: 每 10 秒自动更新

### 数据采集

- **Ticker**: 每 10 秒采集一次所有配置的交易对
- **OHLCV**: 按时间周期自动采集
  - 1m: 每分钟
  - 5m: 每 5 分钟
  - 15m: 每 15 分钟
  - 1h: 每小时
  - 4h: 每 4 小时
  - 1d: 每天
- **Rate Limit**: 自动处理交易所速率限制，失败自动重试

## 快速开始

### 前置要求

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- uv (Python 包管理器)

### 1. 安装 uv

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. 克隆项目并安装依赖

```bash
git clone <repository-url>
cd crypto-market-data-service

# 安装项目依赖
uv sync
```

### 3. 配置环境

```bash
# 复制配置文件
cp .env.example .env
cp config.yaml.example config.yaml

# 编辑 .env 文件，配置数据库和 Redis 连接
# 编辑 config.yaml 文件，配置交易所和交易对
```

#### 环境变量配置 (.env)

```bash
# 数据库配置
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/market_data
DATABASE_POOL_SIZE=10

# Redis 配置
REDIS_URL=redis://localhost:6379/0
OHLCV_CACHE_SIZE=1000        # 每个组合保留的最大条数
TICKER_TTL_SECONDS=10        # Ticker 缓存过期时间（秒）

# API 配置
API_HOST=0.0.0.0
API_PORT=8000

# 数据采集配置
GAP_FILL_ENABLED=true
GAP_FILL_DAYS=7

# YAML 配置文件路径
CONFIG_FILE=config.yaml
```

#### 交易所配置 (config.yaml)

```yaml
# 交易所配置
exchanges:
  - id: binance
    symbols:
      - BTC/USDT
      - ETH/USDT
  
  - id: okx
    symbols:
      - BTC/USDT
      - ETH/USDT
  
  - id: gateio
    symbols:
      - BTC/USDT
      - ETH/USDT

# 支持的时间周期
timeframes:
  - 1m
  - 5m
  - 15m
  - 1h
  - 4h
  - 1d

# 数据补全配置
gap_fill_enabled: true
gap_fill_days: 7
```

### 4. 初始化数据库

```bash
# 创建数据库
createdb market_data

# 运行数据库迁移
uv run alembic upgrade head
```

### 5. 启动服务

```bash
# 开发模式（自动重载）
uv run uvicorn src.main:app --reload

# 生产模式（多进程）
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 6. 访问 API 文档

服务启动后，访问以下地址：

- **服务信息**: http://localhost:8000/
- **健康检查**: http://localhost:8000/health
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## API 端点

### 服务信息

```bash
GET /

# 响应
{
  "service": "Crypto Market Data Service",
  "version": "1.0.0",
  "docs": "/docs",
  "health": "/health"
}
```

### 健康检查

```bash
GET /health

# 响应
{
  "status": "healthy",
  "components": {
    "postgres": "ok",
    "redis": "ok",
    "exchanges": {
      "binance": "ok",
      "okx": "ok",
      "gateio": "ok"
    }
  }
}
```

### K线数据 (OHLCV)

#### 查询单个交易对

```bash
GET /api/v1/ohlcv/{exchange}/{symbol}?timeframe=1h&limit=100&start=1703404800000&end=1703491200000

# 示例
curl "http://localhost:8000/api/v1/ohlcv/binance/BTC/USDT?timeframe=1h&limit=100"

# 响应
{
  "data": [
    {
      "exchange": "binance",
      "symbol": "BTC/USDT",
      "timeframe": "1h",
      "timestamp": 1703404800000,
      "open": "42000.00",
      "high": "42500.00",
      "low": "41800.00",
      "close": "42300.00",
      "volume": "1234.56"
    }
  ],
  "meta": {
    "count": 100,
    "has_more": true,
    "next_cursor": "1703491200000"
  },
  "pagination": {
    "limit": 100,
    "cursor": null
  }
}
```

#### 批量查询多个交易对

```bash
POST /api/v1/ohlcv/batch
Content-Type: application/json

{
  "exchange": "binance",
  "symbols": ["BTC/USDT", "ETH/USDT"],
  "timeframe": "1h",
  "start": 1703404800000,
  "end": 1703491200000,
  "limit": 100
}

# 响应
{
  "results": {
    "BTC/USDT": {
      "data": [...],
      "meta": {...}
    },
    "ETH/USDT": {
      "data": [...],
      "meta": {...}
    }
  },
  "errors": []
}
```

### 实时行情 (Ticker)

#### 查询单个交易对

```bash
GET /api/v1/ticker/{exchange}/{symbol}

# 示例
curl "http://localhost:8000/api/v1/ticker/binance/BTC/USDT"

# 响应
{
  "data": {
    "exchange": "binance",
    "symbol": "BTC/USDT",
    "last": "42300.00",
    "bid": "42299.50",
    "ask": "42300.50",
    "high_24h": "43000.00",
    "low_24h": "41500.00",
    "volume_24h": "12345.67",
    "change_pct_24h": "1.23",
    "timestamp": 1703491200000
  },
  "meta": {
    "cached": true,
    "age_ms": 3500
  }
}
```

#### 查询交易所所有配置的交易对

```bash
GET /api/v1/tickers/{exchange}

# 示例
curl "http://localhost:8000/api/v1/tickers/binance"

# 响应
{
  "data": [
    {
      "exchange": "binance",
      "symbol": "BTC/USDT",
      "last": "42300.00",
      ...
    },
    {
      "exchange": "binance",
      "symbol": "ETH/USDT",
      "last": "2200.00",
      ...
    }
  ]
}
```

### 数据补全 (Gap Filling)

#### 检查数据状态

```bash
# 检查所有1日线数据状态
uv run python check_1d_data.py
```

#### 批量补全

```bash
# 补全最近30天的1日线数据
curl -X POST "http://localhost:8000/api/v1/admin/gap-fill/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "days": 30,
    "timeframes": ["1d"]
  }'

# 补全最近90天的1日线数据
curl -X POST "http://localhost:8000/api/v1/admin/gap-fill/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "days": 90,
    "timeframes": ["1d"]
  }'
```

#### 单个补全

```bash
curl -X POST "http://localhost:8000/api/v1/admin/gap-fill" \
  -H "Content-Type: application/json" \
  -d '{
    "exchange": "binance",
    "symbol": "BTC/USDT",
    "timeframe": "1d",
    "days": 90
  }'
```

**详细文档**: 
- [功能总结](SUMMARY.md)
- [快速参考](QUICK_REFERENCE.md)
- [算法详解](docs/intelligent-gap-detection.md)
- [测试结果](TEST_RESULTS.md)

## 请求追踪 (Correlation ID)

每个 API 请求都会自动生成一个唯一的 Correlation ID，用于追踪整个请求链路。

### 使用方式

```bash
# 发送请求
curl -v http://localhost:8000/api/v1/ticker/binance/BTC/USDT

# 响应头中包含
< x-request-id: 0664ee2f018b43cc8f763fb3679ecc03

# 日志中会显示
2025-12-28T13:16:35.832534Z [info] Request processed correlation_id=0664ee2f018b43cc8f763fb3679ecc03
```

### 优势

- 🔍 **请求追踪**: 通过 Correlation ID 追踪整个请求链路
- 🐛 **问题排查**: 用户报告问题时提供 Request ID，快速定位日志
- 📊 **性能分析**: 分析特定请求的完整执行路径

## 配置说明

### 环境变量 (.env)

| 变量 | 说明 | 默认值 | 范围 |
|------|------|--------|------|
| DATABASE_URL | PostgreSQL 连接字符串 | postgresql://postgres:postgres@localhost:5432/market_data | - |
| DATABASE_POOL_SIZE | 数据库连接池大小 | 10 | 1-50 |
| REDIS_URL | Redis 连接 URL | redis://localhost:6379/0 | - |
| OHLCV_CACHE_SIZE | OHLCV 缓存条数 | 1000 | 100-2000 |
| TICKER_TTL_SECONDS | Ticker 缓存 TTL（秒） | 10 | 1-60 |
| API_HOST | API 监听地址 | 0.0.0.0 | - |
| API_PORT | API 监听端口 | 8000 | 1-65535 |
| RETRY_MAX_ATTEMPTS | 最大重试次数 | 5 | 1-10 |
| GAP_FILL_ENABLED | 是否启用数据补全 | true | true/false |
| GAP_FILL_DAYS | 数据补全天数 | 30 | 1-365 |
| CONFIG_FILE | YAML 配置文件路径 | config.yaml | - |

### 缓存配置优化建议

#### 场景 1: 内存紧张
```bash
OHLCV_CACHE_SIZE=100      # 减少到 100 条
TICKER_TTL_SECONDS=5      # 减少到 5 秒
# 内存占用: ~2.7 MB
```

#### 场景 2: 需要更多历史数据
```bash
OHLCV_CACHE_SIZE=2000     # 增加到 2000 条
TICKER_TTL_SECONDS=10     # 保持 10 秒
# 内存占用: ~54 MB
```

#### 场景 3: 高频交易（需要更新鲜的数据）
```bash
OHLCV_CACHE_SIZE=200      # 减少历史数据
TICKER_TTL_SECONDS=5      # 更频繁更新
```

### 支持的交易所

- **Binance** (binance)
- **OKX** (okx)
- **Gate.io** (gateio)
- 更多交易所可通过 CCXT 库支持

### 支持的时间周期

- 1m, 5m, 15m, 1h, 4h, 1d (默认配置)
- 可在 config.yaml 中自定义

## 开发

### 运行测试

```bash
# 安装开发依赖
uv sync --dev

# 运行所有测试
uv run pytest

# 运行特定测试
uv run pytest tests/unit/
uv run pytest tests/integration/
uv run pytest tests/property/

# 查看覆盖率
uv run pytest --cov=src --cov-report=html
open htmlcov/index.html
```

### 代码检查

```bash
# 类型检查
uv run mypy src

# 代码格式化
uv run ruff format src tests

# 代码检查
uv run ruff check src tests
```

### 数据库迁移

```bash
# 创建新迁移
uv run alembic revision --autogenerate -m "description"

# 应用迁移
uv run alembic upgrade head

# 回滚迁移
uv run alembic downgrade -1

# 查看迁移历史
uv run alembic history
```

## 项目结构

```
.
├── src/
│   ├── api/                    # API 路由
│   │   ├── health.py          # 健康检查
│   │   ├── ohlcv.py           # K线数据 API
│   │   ├── ticker.py          # 实时行情 API
│   │   └── schemas.py         # API 数据模型
│   ├── infrastructure/         # 基础设施层
│   │   ├── cache.py           # Redis 缓存管理
│   │   ├── database.py        # PostgreSQL 连接管理
│   │   ├── exchange.py        # 交易所客户端封装
│   │   └── scheduler.py       # 数据采集调度器
│   ├── models.py              # 数据模型 (OHLCV, Ticker)
│   ├── repositories.py        # 数据访问层
│   ├── dependencies.py        # FastAPI 依赖注入
│   ├── config.py              # 配置管理
│   ├── exceptions.py          # 异常定义
│   └── main.py                # 应用入口
├── tests/                      # 测试
│   ├── unit/                  # 单元测试
│   ├── integration/           # 集成测试
│   └── property/              # 属性测试
├── alembic/                    # 数据库迁移
│   └── versions/              # 迁移脚本
├── .kiro/specs/               # 设计文档
│   └── crypto-market-data-service/
│       ├── requirements.md    # 需求文档
│       ├── design.md          # 设计文档
│       └── tasks.md           # 任务列表
├── .env.example               # 环境变量示例
├── config.yaml.example        # 配置文件示例
├── pyproject.toml             # 项目配置
├── alembic.ini                # Alembic 配置
└── README.md                  # 项目文档
```

## 性能指标

| 指标 | 目标值 | 实际值 |
|------|--------|--------|
| API响应时间（缓存命中） | < 50ms (P95) | ~20ms |
| API响应时间（数据库查询） | < 500ms (P95) | ~200ms |
| 数据采集延迟 | < 5秒 | ~2秒 |
| Redis 内存占用 | 可控 | ~27 MB (满载) |
| 服务可用性 | 99.5% | - |

## 监控和运维

### 查看服务状态

```bash
# 健康检查
curl http://localhost:8000/health

# 查看 Redis 内存使用
redis-cli INFO memory | grep used_memory_human

# 查看 Redis 键数量
redis-cli DBSIZE

# 查看 OHLCV 缓存大小
redis-cli ZCARD "ohlcv:binance:BTC/USDT:1m"
```

### 日志查看

服务使用 structlog 输出结构化日志，每条日志包含：
- 时间戳 (ISO 8601)
- 日志级别
- 消息内容
- Correlation ID (如果是 API 请求)
- 上下文信息

```bash
# 查看服务日志
tail -f logs/app.log

# 按 Correlation ID 过滤日志
grep "correlation_id=xxx" logs/app.log
```

## 故障排查

### 常见问题

#### 1. Gate.io 连接超时

**问题**: 启动时 Gate.io 初始化超时

**原因**: 网络波动或 Gate.io API 响应慢

**解决**: 
- 检查网络连接
- 重启服务通常可以解决
- 如果持续出现，可以暂时在 config.yaml 中注释掉 Gate.io

#### 2. Redis 内存占用过高

**问题**: Redis 内存使用超出预期

**原因**: OHLCV_CACHE_SIZE 设置过大

**解决**:
```bash
# 减小缓存大小
OHLCV_CACHE_SIZE=500  # 从 1000 减少到 500
```

#### 3. 数据库连接池耗尽

**问题**: 出现 "connection pool exhausted" 错误

**原因**: 并发请求过多

**解决**:
```bash
# 增加连接池大小
DATABASE_POOL_SIZE=20  # 从 10 增加到 20
```

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

### 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 开发规范

- 遵循 PEP 8 代码风格
- 使用 type hints
- 编写单元测试和集成测试
- 更新相关文档

## 联系方式

如有问题或建议，请通过以下方式联系：

- 提交 Issue
- 发送 Pull Request
- 邮件联系: [your-email@example.com]

## 致谢

感谢以下开源项目：

- [FastAPI](https://fastapi.tiangolo.com/)
- [CCXT](https://github.com/ccxt/ccxt)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [Redis](https://redis.io/)
- [structlog](https://www.structlog.org/)
- [asgi-correlation-id](https://github.com/snok/asgi-correlation-id)
