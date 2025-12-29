# Requirements Document

## Introduction

本文档定义了数字货币交易数据服务的需求规范。该服务为量化交易系统提供统一的市场数据访问能力。

**核心价值**：让量化策略开发者不需要关心数据从哪来、怎么存，只需通过API获取所需数据。

**整体规划**：
- 第一期：交易所K线和Ticker数据（REST API）
- 第二期：链上数据、WebSocket实时推送
- 第三期：舆情数据、消息队列集成

**第一期范围**：
- 交易所K线数据（OHLCV）采集、存储、查询
- 实时Ticker数据缓存和查询

**技术栈**：Python 3.11+ / uv / FastAPI / PostgreSQL / Redis / CCXT / SQLAlchemy / Alembic

## Glossary

- **OHLCV**: K线数据（Open, High, Low, Close, Volume）
- **Ticker**: 实时行情快照（当前价、24h统计）
- **Timeframe**: K线周期（1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M）
- **Exchange**: 交易所（binance, okx等）
- **Symbol**: 交易对（BTC/USDT, ETH/USDT等）
- **Market_Data_Service**: 本系统的统称

## Data Models

### OHLCV

```json
{
  "exchange": "binance",
  "symbol": "BTC/USDT",
  "timeframe": "1h",
  "timestamp": 1703404800000,
  "open": "43250.50",
  "high": "43500.00",
  "low": "43100.00",
  "close": "43350.25",
  "volume": "1234.5678"
}
```

### Ticker

```json
{
  "exchange": "binance",
  "symbol": "BTC/USDT",
  "last": "43350.25",
  "bid": "43350.00",
  "ask": "43350.50",
  "high_24h": "44000.00",
  "low_24h": "42500.00",
  "volume_24h": "50000.1234",
  "change_pct_24h": "2.35",
  "timestamp": 1703404800000
}
```

## Non-Functional Requirements

### 性能要求

| 指标 | 目标值 | 测量条件 |
|------|--------|----------|
| API响应时间（缓存命中） | < 50ms (P95) | 100 QPS |
| API响应时间（数据库查询） | < 500ms (P95) | 100 QPS |
| 数据采集延迟 | < 5秒 | 相对于交易所数据 |
| 并发连接数 | 100 | 同时在线客户端 |

### 可用性要求

| 指标 | 目标值 |
|------|--------|
| 服务可用性 | 99.5% |
| 数据完整性 | 99.9%（允许0.1%缺口） |
| 故障恢复时间 | < 5分钟 |

### 容量要求

| 指标 | 限制 |
|------|------|
| 单次查询最大记录数 | 1000条 |
| 批量查询最大交易对数 | 20个 |
| 单交易所最大交易对数 | 100个 |
| 历史数据保留时间 | 1年 |
| 单次查询最大时间范围 | 30天 |

## Functional Requirements

### Requirement 1: K线数据查询

**User Story:** As a quantitative trader, I want to query historical OHLCV data via REST API, so that I can analyze markets and backtest strategies.

#### Acceptance Criteria

1. WHEN GET /api/v1/ohlcv/{exchange}/{symbol} is called with params (timeframe, start, end) THEN the Market_Data_Service SHALL return OHLCV list in JSON format
2. WHEN the requested time range exceeds 1000 records THEN the Market_Data_Service SHALL paginate with cursor-based pagination
3. WHEN exchange, symbol, or timeframe is invalid THEN the Market_Data_Service SHALL return HTTP 400 with error code and message
4. WHEN the requested time range exceeds 30 days THEN the Market_Data_Service SHALL return HTTP 400 with error message
5. THE response format SHALL be: {"data": [...], "pagination": {"next_cursor": "..."}, "meta": {"cached": bool, "query_ms": int}}
6. WHEN OHLCV data is serialized THEN the Market_Data_Service SHALL preserve 8 decimal places for prices and 4 decimal places for volumes

### Requirement 2: Ticker数据查询

**User Story:** As a quantitative trader, I want to query real-time ticker data, so that I can monitor market conditions.

#### Acceptance Criteria

1. WHEN GET /api/v1/ticker/{exchange}/{symbol} is called THEN the Market_Data_Service SHALL return current Ticker data
2. WHEN Ticker is not available in cache THEN the Market_Data_Service SHALL fetch from exchange and cache it
3. WHEN GET /api/v1/tickers/{exchange} is called THEN the Market_Data_Service SHALL return all configured tickers for that exchange
4. THE response format SHALL be: {"data": {...}, "meta": {"cached": bool, "age_ms": int}}

### Requirement 3: 批量数据查询

**User Story:** As a quantitative trader, I want to query multiple symbols at once, so that portfolio analysis is efficient.

#### Acceptance Criteria

1. WHEN POST /api/v1/ohlcv/batch is called with symbols list THEN the Market_Data_Service SHALL return data for all symbols
2. WHEN any symbol fails THEN the Market_Data_Service SHALL return partial results with errors array
3. WHEN symbols count exceeds 20 THEN the Market_Data_Service SHALL return HTTP 400 error
4. THE response format SHALL be: {"data": {"BTC/USDT": [...], ...}, "errors": [{"symbol": "...", "error": "..."}]}

### Requirement 4: 数据自动采集

**User Story:** As a system administrator, I want the service to automatically collect market data, so that the database stays current.

#### Acceptance Criteria

1. WHEN the service starts THEN it SHALL begin collecting OHLCV data for all configured (exchange, symbol, timeframe) combinations
2. THE OHLCV collection interval SHALL match the timeframe (5m data collected every 5 minutes)
3. THE Ticker collection interval SHALL be 10 seconds for all configured symbols
4. WHEN collection fails THEN the service SHALL retry with exponential backoff (max 5 retries)
5. WHEN exchange rate limit is exceeded THEN the service SHALL pause collection for that exchange

### Requirement 5: 数据完整性保障

**User Story:** As a quantitative trader, I want complete data without gaps, so that backtesting is accurate.

#### Acceptance Criteria

1. WHEN the service starts THEN it SHALL check for data gaps in the last 7 days
2. WHEN a gap is detected THEN the service SHALL fetch missing data from exchange
3. WHILE gap filling runs THEN normal collection SHALL continue without blocking
4. WHEN gap filling completes THEN the service SHALL log statistics

### Requirement 6: 配置管理

**User Story:** As a system administrator, I want to configure the service via YAML file, so that I can control behavior without code changes.

#### Acceptance Criteria

1. THE service SHALL load configuration from config.yaml at startup
2. WHEN configuration is invalid THEN the service SHALL fail fast with clear error message
3. THE configuration SHALL support environment variable substitution for sensitive values
4. WHEN config file changes THEN the service SHALL support hot reload via API endpoint

### Requirement 7: 健康监控

**User Story:** As a system operator, I want to monitor service health, so that I can ensure reliability.

#### Acceptance Criteria

1. WHEN GET /health is called THEN the Market_Data_Service SHALL return status of all components
2. WHEN any critical component is unhealthy THEN the Market_Data_Service SHALL return HTTP 503
3. THE service SHALL expose Prometheus metrics at /metrics endpoint
4. THE metrics SHALL include: request_latency, cache_hit_ratio, collection_success_ratio, data_freshness

### Requirement 8: 数据存储

**User Story:** As a system architect, I want reliable data storage, so that historical data is preserved.

#### Acceptance Criteria

1. THE service SHALL store OHLCV data in PostgreSQL with unique constraint on (exchange, symbol, timeframe, timestamp)
2. WHEN writing duplicate data THEN the service SHALL use upsert to update existing records
3. THE service SHALL cache recent OHLCV data in Redis for fast access
4. THE service SHALL cache Ticker data in Redis with 10 second TTL
5. WHEN cache is unavailable THEN the service SHALL fallback to database (for OHLCV) or exchange (for Ticker)
