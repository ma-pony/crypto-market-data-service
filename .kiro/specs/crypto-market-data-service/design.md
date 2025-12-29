# Design Document: Crypto Market Data Service

## Overview

本设计文档描述数字货币交易数据服务的技术实现方案。

### 设计目标

1. **高性能**：缓存命中时 P95 < 50ms
2. **高可用**：单组件故障时优雅降级
3. **可维护**：清晰的代码结构，易于理解和修改
4. **可扩展**：预留扩展点，但不过度抽象

### 设计原则

1. **KISS** - 保持简单，第一期不需要复杂的分层
2. **YAGNI** - 不提前实现不需要的功能
3. **配置驱动** - 行为通过配置控制，不硬编码
4. **失败友好** - 优雅处理错误，提供有意义的错误信息

### 技术选型

| 组件 | 技术 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | 生态丰富，CCXT原生支持 |
| 包管理 | uv | 快速、现代 |
| Web框架 | FastAPI | 高性能、自动文档 |
| ORM | SQLAlchemy 2.0 | 类型安全、异步支持 |
| 迁移 | Alembic | SQLAlchemy官方工具 |
| 交易所 | CCXT | 统一的多交易所接口 |
| 调度 | APScheduler | 成熟的调度库 |
| 数据库 | PostgreSQL 15+ | 可靠、性能好 |
| 缓存 | Redis 7+ | 高性能 |
| 配置 | Pydantic Settings | 类型安全、环境变量支持 |
| 日志 | structlog | 结构化日志 |

## Architecture

### 简化的三层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        API Layer (FastAPI)                           │
│  Routes: /api/v1/ohlcv, /api/v1/ticker, /health, /metrics           │
├─────────────────────────────────────────────────────────────────────┤
│                       Domain Layer                                   │
│  ├─ Models: OHLCV, Ticker                                           │
│  ├─ Repositories: OHLCVRepository, TickerRepository                 │
│  └─ Services: CollectionService, GapFillService                     │
├─────────────────────────────────────────────────────────────────────┤
│                    Infrastructure Layer                              │
│  ├─ Database (SQLAlchemy + asyncpg)                                 │
│  ├─ Cache (redis-py)                                                │
│  ├─ ExchangeClient (CCXT)                                           │
│  └─ Scheduler (APScheduler)                                         │
└─────────────────────────────────────────────────────────────────────┘
```

### 项目结构

```
src/
├── main.py                 # 应用入口 + lifespan
├── config.py               # 配置定义 (Pydantic Settings)
├── exceptions.py           # 异常定义
├── models.py               # 领域模型 + ORM模型
├── repositories.py         # 数据访问
├── services.py             # 业务逻辑
├── dependencies.py         # 依赖注入定义 (FastAPI Depends)
├── api/
│   ├── __init__.py
│   ├── ohlcv.py            # K线路由 (APIRouter)
│   ├── ticker.py           # Ticker路由 (APIRouter)
│   ├── health.py           # 健康检查路由 (APIRouter)
│   └── schemas.py          # 请求/响应模型
├── infrastructure/
│   ├── database.py         # 数据库连接
│   ├── cache.py            # Redis缓存
│   ├── exchange.py         # 交易所客户端
│   └── scheduler.py        # 调度器
├── alembic/
│   ├── versions/
│   └── env.py
└── alembic.ini
```

### 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 数据一致性 | 最终一致 | 缓存和数据库可能短暂不一致，可接受 |
| 缓存策略 | Write-through | 写入时同时更新缓存和数据库 |
| 错误恢复 | 重试 + 日志 | 采集失败重试，持续失败记录日志 |
| 多实例部署 | 暂不支持 | 第一期单实例，后续可加分布式锁 |


## Components

### 1. Configuration

```python
from pydantic_settings import BaseSettings
from pydantic import BaseModel, Field
from typing import List, Optional
from functools import lru_cache

class ExchangeConfig(BaseModel):
    """交易所配置（嵌套配置不应继承 BaseSettings）"""
    id: str
    api_key: Optional[str] = None
    secret: Optional[str] = None
    symbols: List[str]

class Settings(BaseSettings):
    """应用配置"""
    
    # 数据库
    database_url: str = Field(..., description="PostgreSQL连接字符串")
    database_pool_size: int = Field(default=10, ge=1, le=50)
    
    # Redis
    redis_url: str = Field(..., description="Redis连接URL")
    ohlcv_cache_size: int = Field(default=500, ge=100, le=2000)
    ticker_ttl_seconds: int = Field(default=10, ge=1, le=60)
    
    # API
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    
    # 调度
    retry_max_attempts: int = Field(default=5, ge=1, le=10)
    
    # 数据采集
    exchanges: List[ExchangeConfig]
    timeframes: List[str] = Field(default=["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"])
    gap_fill_enabled: bool = Field(default=True)
    gap_fill_days: int = Field(default=7, ge=1, le=30)
    
    class Config:
        env_file = ".env"
        env_nested_delimiter = "__"

@lru_cache
def get_settings() -> Settings:
    """获取配置单例（使用 lru_cache 避免重复加载）"""
    return Settings()
```

### 2. Domain Models

使用 SQLAlchemy 2.0 Mapped 类型，同时作为领域模型和 ORM 模型：

```python
from sqlalchemy import String, BigInteger, Numeric, DateTime, Index, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func
from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
import uuid

class Base(DeclarativeBase):
    pass

class OHLCV(Base):
    """K线数据模型"""
    __tablename__ = "ohlcv"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    __table_args__ = (
        UniqueConstraint('exchange', 'symbol', 'timeframe', 'timestamp', name='uq_ohlcv_key'),
        Index('idx_ohlcv_lookup', 'exchange', 'symbol', 'timeframe', 'timestamp'),
    )
    
    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "OHLCV":
        return cls(
            exchange=data["exchange"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            timestamp=data["timestamp"],
            open=Decimal(data["open"]),
            high=Decimal(data["high"]),
            low=Decimal(data["low"]),
            close=Decimal(data["close"]),
            volume=Decimal(data["volume"]),
        )

@dataclass
class Ticker:
    """Ticker数据模型（不持久化）"""
    exchange: str
    symbol: str
    last: Decimal
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    high_24h: Optional[Decimal] = None
    low_24h: Optional[Decimal] = None
    volume_24h: Optional[Decimal] = None
    change_pct_24h: Optional[Decimal] = None
    timestamp: int = 0
    
    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "last": str(self.last),
            "bid": str(self.bid) if self.bid else None,
            "ask": str(self.ask) if self.ask else None,
            "high_24h": str(self.high_24h) if self.high_24h else None,
            "low_24h": str(self.low_24h) if self.low_24h else None,
            "volume_24h": str(self.volume_24h) if self.volume_24h else None,
            "change_pct_24h": str(self.change_pct_24h) if self.change_pct_24h else None,
            "timestamp": self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Ticker":
        return cls(
            exchange=data["exchange"],
            symbol=data["symbol"],
            last=Decimal(data["last"]),
            bid=Decimal(data["bid"]) if data.get("bid") else None,
            ask=Decimal(data["ask"]) if data.get("ask") else None,
            high_24h=Decimal(data["high_24h"]) if data.get("high_24h") else None,
            low_24h=Decimal(data["low_24h"]) if data.get("low_24h") else None,
            volume_24h=Decimal(data["volume_24h"]) if data.get("volume_24h") else None,
            change_pct_24h=Decimal(data["change_pct_24h"]) if data.get("change_pct_24h") else None,
            timestamp=data["timestamp"],
        )
```


### 3. Exceptions

```python
from enum import Enum
from typing import Optional, Any

class ErrorCode(str, Enum):
    # 客户端错误
    INVALID_SYMBOL = "INVALID_SYMBOL"
    INVALID_TIMEFRAME = "INVALID_TIMEFRAME"
    INVALID_TIME_RANGE = "INVALID_TIME_RANGE"
    BATCH_SIZE_EXCEEDED = "BATCH_SIZE_EXCEEDED"
    
    # 服务端错误
    EXCHANGE_ERROR = "EXCHANGE_ERROR"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    CACHE_ERROR = "CACHE_ERROR"

class MarketDataError(Exception):
    def __init__(self, code: ErrorCode, message: str, details: Optional[dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)
    
    def to_dict(self) -> dict:
        return {"error": {"code": self.code.value, "message": self.message, "details": self.details}}

class ClientError(MarketDataError):
    """客户端错误 (4xx)"""
    pass

class ServerError(MarketDataError):
    """服务端错误 (5xx)"""
    pass

class RateLimitError(ServerError):
    def __init__(self, exchange: str, retry_after: int):
        super().__init__(ErrorCode.RATE_LIMIT_ERROR, f"Rate limit exceeded for {exchange}", 
                        {"exchange": exchange, "retry_after_seconds": retry_after})
        self.retry_after = retry_after
```

### 4. Infrastructure

#### Database

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from contextlib import asynccontextmanager

class Database:
    def __init__(self, url: str, pool_size: int = 10):
        async_url = url.replace("postgresql://", "postgresql+asyncpg://")
        self.engine = create_async_engine(async_url, pool_size=pool_size)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
    
    @asynccontextmanager
    async def session(self):
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    
    async def health_check(self) -> bool:
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(lambda _: None)
            return True
        except Exception:
            return False
    
    async def dispose(self):
        await self.engine.dispose()
```

#### Cache

```python
import redis.asyncio as redis
import json
from typing import List, Optional

class Cache:
    def __init__(self, url: str, ohlcv_cache_size: int = 500, ticker_ttl: int = 10):
        self.url = url
        self.ohlcv_cache_size = ohlcv_cache_size
        self.ticker_ttl = ticker_ttl
        self._client: Optional[redis.Redis] = None
    
    async def connect(self):
        self._client = redis.from_url(self.url)
    
    async def disconnect(self):
        if self._client:
            await self._client.close()
    
    async def health_check(self) -> bool:
        try:
            await self._client.ping()
            return True
        except Exception:
            return False
    
    # OHLCV
    def _ohlcv_key(self, exchange: str, symbol: str, timeframe: str) -> str:
        return f"ohlcv:{exchange}:{symbol}:{timeframe}"
    
    async def cache_ohlcv(self, records: List[OHLCV]):
        if not records:
            return
        by_key = {}
        for r in records:
            key = self._ohlcv_key(r.exchange, r.symbol, r.timeframe)
            by_key.setdefault(key, []).append(r)
        
        pipe = self._client.pipeline()
        for key, recs in by_key.items():
            for r in recs:
                pipe.zadd(key, {json.dumps(r.to_dict()): r.timestamp})
            pipe.zremrangebyrank(key, 0, -(self.ohlcv_cache_size + 1))
        await pipe.execute()
    
    async def get_ohlcv(self, exchange: str, symbol: str, timeframe: str,
                        start: Optional[int] = None, end: Optional[int] = None, limit: int = 500) -> List[OHLCV]:
        key = self._ohlcv_key(exchange, symbol, timeframe)
        data = await self._client.zrangebyscore(key, start or "-inf", end or "+inf", start=0, num=limit)
        return [OHLCV.from_dict(json.loads(item)) for item in data]
    
    # Ticker
    def _ticker_key(self, exchange: str, symbol: str) -> str:
        return f"ticker:{exchange}:{symbol}"
    
    async def cache_ticker(self, ticker: Ticker):
        key = self._ticker_key(ticker.exchange, ticker.symbol)
        await self._client.setex(key, self.ticker_ttl, json.dumps(ticker.to_dict()))
    
    async def get_ticker(self, exchange: str, symbol: str) -> Optional[Ticker]:
        key = self._ticker_key(exchange, symbol)
        data = await self._client.get(key)
        return Ticker.from_dict(json.loads(data)) if data else None
```

#### ExchangeClient

```python
import ccxt.async_support as ccxt
from decimal import Decimal
import time

class ExchangeClient:
    TIMEFRAME_MS = {
        "1m": 60000, "3m": 180000, "5m": 300000, "15m": 900000, "30m": 1800000,
        "1h": 3600000, "2h": 7200000, "4h": 14400000, "6h": 21600000, "8h": 28800000,
        "12h": 43200000, "1d": 86400000, "3d": 259200000, "1w": 604800000, "1M": 2592000000
    }
    
    def __init__(self, exchange_id: str, api_key: str = None, secret: str = None):
        self.exchange_id = exchange_id
        exchange_class = getattr(ccxt, exchange_id)
        self._client = exchange_class({"apiKey": api_key, "secret": secret, "enableRateLimit": True})
    
    async def connect(self):
        await self._client.load_markets()
    
    async def disconnect(self):
        await self._client.close()
    
    async def health_check(self) -> bool:
        try:
            await self._client.fetch_time()
            return True
        except Exception:
            return False
    
    async def fetch_ohlcv(self, symbol: str, timeframe: str, since: int = None, limit: int = 500) -> List[OHLCV]:
        try:
            data = await self._client.fetch_ohlcv(symbol, timeframe, since, limit)
            return [OHLCV(exchange=self.exchange_id, symbol=symbol, timeframe=timeframe,
                        timestamp=int(r[0]), open=Decimal(str(r[1])), high=Decimal(str(r[2])),
                        low=Decimal(str(r[3])), close=Decimal(str(r[4])), volume=Decimal(str(r[5])))
                   for r in data]
        except ccxt.RateLimitExceeded:
            raise RateLimitError(self.exchange_id, 60)
        except ccxt.BaseError as e:
            raise ServerError(ErrorCode.EXCHANGE_ERROR, str(e), {"exchange": self.exchange_id})
    
    async def fetch_ticker(self, symbol: str) -> Ticker:
        try:
            d = await self._client.fetch_ticker(symbol)
            return Ticker(exchange=self.exchange_id, symbol=symbol, last=Decimal(str(d["last"])),
                         bid=Decimal(str(d["bid"])) if d.get("bid") else None,
                         ask=Decimal(str(d["ask"])) if d.get("ask") else None,
                         high_24h=Decimal(str(d["high"])) if d.get("high") else None,
                         low_24h=Decimal(str(d["low"])) if d.get("low") else None,
                         volume_24h=Decimal(str(d["quoteVolume"])) if d.get("quoteVolume") else None,
                         change_pct_24h=Decimal(str(d["percentage"])) if d.get("percentage") else None,
                         timestamp=int(d["timestamp"]) if d.get("timestamp") else int(time.time() * 1000))
        except ccxt.RateLimitExceeded:
            raise RateLimitError(self.exchange_id, 60)
        except ccxt.BaseError as e:
            raise ServerError(ErrorCode.EXCHANGE_ERROR, str(e), {"exchange": self.exchange_id})
```


### 5. Repositories

使用依赖注入的 session，Repository 不再内部管理数据库会话：

```python
from sqlalchemy import select, and_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Tuple

class OHLCVRepository:
    """K线数据仓库（使用注入的 session）"""
    
    def __init__(self, cache: Cache):
        self.cache = cache
    
    async def save(self, session: AsyncSession, records: List[OHLCV]) -> int:
        """批量保存 OHLCV 数据（使用批量 upsert 提高效率）"""
        if not records:
            return 0
        
        # 批量 upsert - 一次性插入所有记录
        stmt = insert(OHLCV).values([
            {
                "exchange": r.exchange,
                "symbol": r.symbol,
                "timeframe": r.timeframe,
                "timestamp": r.timestamp,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in records
        ]).on_conflict_do_update(
            constraint='uq_ohlcv_key',
            set_={
                'open': insert(OHLCV).excluded.open,
                'high': insert(OHLCV).excluded.high,
                'low': insert(OHLCV).excluded.low,
                'close': insert(OHLCV).excluded.close,
                'volume': insert(OHLCV).excluded.volume,
            }
        )
        await session.execute(stmt)
        
        # 更新缓存
        await self.cache.cache_ohlcv(records)
        return len(records)
    
    async def find(self, session: AsyncSession, exchange: str, symbol: str, timeframe: str,
                   start: Optional[int] = None, end: Optional[int] = None,
                   limit: int = 1000, cursor: Optional[str] = None) -> Tuple[List[OHLCV], Optional[str], bool]:
        """返回 (数据, 下一页游标, 是否来自缓存)"""
        
        # 尝试缓存（仅当无游标且 limit 较小时）
        if not cursor and limit <= 500:
            cached = await self.cache.get_ohlcv(exchange, symbol, timeframe, start, end, limit)
            if cached:
                return cached, None, True
        
        # 查询数据库
        conditions = [OHLCV.exchange == exchange, OHLCV.symbol == symbol, OHLCV.timeframe == timeframe]
        if start: conditions.append(OHLCV.timestamp >= start)
        if end: conditions.append(OHLCV.timestamp <= end)
        if cursor: conditions.append(OHLCV.timestamp > int(cursor))
        
        stmt = select(OHLCV).where(and_(*conditions)).order_by(OHLCV.timestamp.asc()).limit(limit + 1)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        
        has_more = len(rows) > limit
        records = list(rows[:limit])
        next_cursor = str(records[-1].timestamp) if has_more and records else None
        return records, next_cursor, False


class TickerRepository:
    """Ticker数据仓库（不需要数据库，仅缓存）"""
    
    def __init__(self, cache: Cache, clients: dict[str, ExchangeClient]):
        self.cache = cache
        self.clients = clients
    
    async def save(self, ticker: Ticker):
        await self.cache.cache_ticker(ticker)
    
    async def find(self, exchange: str, symbol: str) -> Tuple[Optional[Ticker], bool]:
        """返回 (数据, 是否来自缓存)"""
        cached = await self.cache.get_ticker(exchange, symbol)
        if cached:
            return cached, True
        
        client = self.clients.get(exchange)
        if not client:
            raise ClientError(ErrorCode.INVALID_SYMBOL, f"Unknown exchange: {exchange}")
        
        ticker = await client.fetch_ticker(symbol)
        await self.save(ticker)
        return ticker, False
```

### 6. Dependencies (FastAPI Best Practice)

使用 `app.state` + `Request` 模式进行依赖注入，数据库会话通过依赖注入：

```python
# dependencies.py
from typing import Annotated, AsyncGenerator
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .infrastructure.database import Database
from .infrastructure.cache import Cache
from .infrastructure.exchange import ExchangeClient
from .repositories import OHLCVRepository, TickerRepository
from .exceptions import ClientError, ErrorCode

# 从 app.state 获取依赖（在 lifespan 中初始化）
def get_db(request: Request) -> Database:
    return request.app.state.db

def get_cache(request: Request) -> Cache:
    return request.app.state.cache

def get_exchange_clients(request: Request) -> dict[str, ExchangeClient]:
    return request.app.state.clients

def get_ohlcv_repo(request: Request) -> OHLCVRepository:
    return request.app.state.ohlcv_repo

def get_ticker_repo(request: Request) -> TickerRepository:
    return request.app.state.ticker_repo

# 数据库会话依赖（核心依赖注入）
async def get_db_session(db: Annotated[Database, Depends(get_db)]) -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话（带自动提交/回滚）
    
    - 每个请求一个会话
    - 请求结束自动提交或回滚
    - 支持跨 Repository 事务
    """
    async with db.session() as session:
        yield session

# 验证依赖
def validate_exchange(
    exchange: str,
    clients: Annotated[dict[str, ExchangeClient], Depends(get_exchange_clients)],
) -> str:
    """验证交易所是否在配置中"""
    if exchange not in clients:
        raise ClientError(ErrorCode.INVALID_SYMBOL, f"Unknown exchange: {exchange}")
    return exchange

def validate_symbol(symbol: str) -> str:
    """验证交易对格式（BASE/QUOTE）"""
    if "/" not in symbol or len(symbol.split("/")) != 2:
        raise ClientError(ErrorCode.INVALID_SYMBOL, f"Invalid symbol format: {symbol}")
    return symbol

# 类型别名（简化路由函数签名）
DbDep = Annotated[Database, Depends(get_db)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CacheDep = Annotated[Cache, Depends(get_cache)]
ExchangeClients = Annotated[dict[str, ExchangeClient], Depends(get_exchange_clients)]
OHLCVRepo = Annotated[OHLCVRepository, Depends(get_ohlcv_repo)]
TickerRepo = Annotated[TickerRepository, Depends(get_ticker_repo)]
ValidExchange = Annotated[str, Depends(validate_exchange)]
ValidSymbol = Annotated[str, Depends(validate_symbol)]
```

### 7. API Routes (Modular with APIRouter)

使用 `APIRouter` 模块化路由，数据库会话通过依赖注入：

```python
# api/ohlcv.py
from typing import Annotated, Optional
from fastapi import APIRouter, Query
import time

from ..dependencies import OHLCVRepo, DbSession
from ..exceptions import ClientError, ErrorCode
from .schemas import OHLCVListResponse, OHLCVResponse, BatchRequest

router = APIRouter(prefix="/api/v1", tags=["OHLCV"])

VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}

@router.get("/ohlcv/{exchange}/{symbol}", response_model=OHLCVListResponse)
async def get_ohlcv(
    exchange: str,
    symbol: str,
    session: DbSession,
    ohlcv_repo: OHLCVRepo,
    timeframe: Annotated[str, Query(pattern="^(1m|3m|5m|15m|30m|1h|2h|4h|6h|8h|12h|1d|3d|1w|1M)$")],
    start: Optional[int] = None,
    end: Optional[int] = None,
    limit: Annotated[int, Query(le=1000)] = 500,
    cursor: Optional[str] = None,
):
    t0 = time.time()
    records, next_cursor, cached = await ohlcv_repo.find(session, exchange, symbol, timeframe, start, end, limit, cursor)
    return OHLCVListResponse(
        data=[OHLCVResponse(**r.to_dict()) for r in records],
        pagination={"next_cursor": next_cursor},
        meta={"cached": cached, "query_ms": int((time.time() - t0) * 1000)}
    )

@router.post("/ohlcv/batch")
async def batch_ohlcv(req: BatchRequest, session: DbSession, ohlcv_repo: OHLCVRepo):
    if len(req.symbols) > 20:
        raise ClientError(ErrorCode.BATCH_SIZE_EXCEEDED, "Maximum 20 symbols")
    
    data, errors = {}, []
    for symbol in req.symbols:
        try:
            records, _, _ = await ohlcv_repo.find(session, req.exchange, symbol, req.timeframe, req.start, req.end)
            data[symbol] = [OHLCVResponse(**r.to_dict()) for r in records]
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})
    return {"data": data, "errors": errors}
```

```python
# api/ticker.py
from fastapi import APIRouter
import time

from ..dependencies import TickerRepo
from .schemas import TickerSingleResponse, TickerResponse

router = APIRouter(prefix="/api/v1", tags=["Ticker"])

@router.get("/ticker/{exchange}/{symbol}", response_model=TickerSingleResponse)
async def get_ticker(exchange: str, symbol: str, ticker_repo: TickerRepo):
    t0 = time.time()
    ticker, cached = await ticker_repo.find(exchange, symbol)
    return TickerSingleResponse(
        data=TickerResponse(**ticker.to_dict()),
        meta={"cached": cached, "query_ms": int((time.time() - t0) * 1000)}
    )
```

```python
# api/health.py
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..dependencies import CacheDep, ExchangeClients

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health(request: Request, cache: CacheDep, clients: ExchangeClients):
    """健康检查 - 从 app.state 获取 db"""
    db = request.app.state.db
    
    status = {
        "postgres": "ok" if await db.health_check() else "error",
        "redis": "ok" if await cache.health_check() else "error",
        "exchanges": {eid: "ok" if await c.health_check() else "error" for eid, c in clients.items()}
    }
    overall = "healthy" if status["postgres"] == "ok" and status["redis"] == "ok" else "degraded"
    return JSONResponse(
        status_code=200 if overall == "healthy" else 503,
        content={"status": overall, "components": status}
    )
```

```python
# api/schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional

class OHLCVResponse(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
    timestamp: int
    open: str
    high: str
    low: str
    close: str
    volume: str

class TickerResponse(BaseModel):
    exchange: str
    symbol: str
    last: str
    bid: Optional[str] = None
    ask: Optional[str] = None
    high_24h: Optional[str] = None
    low_24h: Optional[str] = None
    volume_24h: Optional[str] = None
    change_pct_24h: Optional[str] = None
    timestamp: int

class OHLCVListResponse(BaseModel):
    data: List[OHLCVResponse]
    pagination: dict
    meta: dict

class TickerSingleResponse(BaseModel):
    data: TickerResponse
    meta: dict

class BatchRequest(BaseModel):
    exchange: str
    symbols: List[str] = Field(..., max_length=20)
    timeframe: str
    start: Optional[int] = None
    end: Optional[int] = None
```

### 8. Application Entry Point (Lifespan Pattern)

使用 FastAPI 推荐的 `lifespan` 上下文管理器 + `app.state` 管理应用生命周期：

```python
# main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import get_settings
from .infrastructure.database import Database
from .infrastructure.cache import Cache
from .infrastructure.exchange import ExchangeClient
from .infrastructure.scheduler import CollectionScheduler
from .repositories import OHLCVRepository, TickerRepository
from .exceptions import MarketDataError, ClientError
from .api import ohlcv, ticker, health

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 - 使用 app.state 存储依赖"""
    settings = get_settings()
    
    # Startup: 初始化所有组件并存储到 app.state
    app.state.db = Database(settings.database_url, settings.database_pool_size)
    app.state.cache = Cache(settings.redis_url, settings.ohlcv_cache_size, settings.ticker_ttl_seconds)
    await app.state.cache.connect()
    
    app.state.clients = {}
    for ex in settings.exchanges:
        client = ExchangeClient(ex.id, ex.api_key, ex.secret)
        await client.connect()
        app.state.clients[ex.id] = client
    
    # 初始化 Repository（不再需要 db，使用注入的 session）
    app.state.ohlcv_repo = OHLCVRepository(app.state.cache)
    app.state.ticker_repo = TickerRepository(app.state.cache, app.state.clients)
    
    # 启动调度器（调度器内部管理 session）
    app.state.scheduler = CollectionScheduler(
        app.state.db, app.state.clients, app.state.ohlcv_repo, app.state.ticker_repo
    )
    app.state.scheduler.start(settings.exchanges, settings.timeframes)
    
    yield  # 应用运行中
    
    # Shutdown: 清理资源
    app.state.scheduler.stop()
    for client in app.state.clients.values():
        await client.disconnect()
    await app.state.cache.disconnect()
    await app.state.db.dispose()

# 创建应用
app = FastAPI(
    title="Crypto Market Data Service",
    version="1.0.0",
    lifespan=lifespan,
)

# 注册路由
app.include_router(ohlcv.router)
app.include_router(ticker.router)
app.include_router(health.router)

# 全局异常处理
@app.exception_handler(MarketDataError)
async def error_handler(request, exc: MarketDataError):
    status = 400 if isinstance(exc, ClientError) else 500
    return JSONResponse(status_code=status, content=exc.to_dict())
```


### 9. Scheduler

调度器内部管理数据库会话（后台任务不通过 FastAPI 依赖注入）：

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import time
import structlog

logger = structlog.get_logger()

class CollectionScheduler:
    """数据采集调度器（内部管理数据库会话）"""
    
    TIMEFRAME_SECONDS = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
        "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800, "1M": 2592000
    }
    
    def __init__(self, db: Database, clients: dict[str, ExchangeClient], 
                 ohlcv_repo: OHLCVRepository, ticker_repo: TickerRepository):
        self.db = db
        self.clients = clients
        self.ohlcv_repo = ohlcv_repo
        self.ticker_repo = ticker_repo
        self._scheduler = AsyncIOScheduler()
        self._paused: dict[str, float] = {}
    
    def _is_paused(self, exchange: str) -> bool:
        if exchange in self._paused and time.time() < self._paused[exchange]:
            return True
        self._paused.pop(exchange, None)
        return False
    
    async def _collect_ohlcv(self, exchange: str, symbol: str, timeframe: str):
        """采集 OHLCV 数据（内部管理会话）"""
        if self._is_paused(exchange):
            return
        try:
            records = await self.clients[exchange].fetch_ohlcv(symbol, timeframe, limit=10)
            # 后台任务内部管理会话
            async with self.db.session() as session:
                await self.ohlcv_repo.save(session, records)
            logger.info("ohlcv_collected", exchange=exchange, symbol=symbol, count=len(records))
        except RateLimitError as e:
            self._paused[exchange] = time.time() + e.retry_after
            logger.warning("rate_limited", exchange=exchange)
        except Exception as e:
            logger.error("collection_failed", exchange=exchange, symbol=symbol, error=str(e))
    
    async def _collect_ticker(self, exchange: str, symbol: str):
        """采集 Ticker 数据（不需要数据库）"""
        if self._is_paused(exchange):
            return
        try:
            ticker = await self.clients[exchange].fetch_ticker(symbol)
            await self.ticker_repo.save(ticker)
        except RateLimitError as e:
            self._paused[exchange] = time.time() + e.retry_after
        except Exception as e:
            logger.error("ticker_failed", exchange=exchange, symbol=symbol, error=str(e))
    
    def start(self, exchanges: List[ExchangeConfig], timeframes: List[str]):
        for ex in exchanges:
            for symbol in ex.symbols:
                for tf in timeframes:
                    self._scheduler.add_job(self._collect_ohlcv, IntervalTrigger(seconds=self.TIMEFRAME_SECONDS[tf]),
                                           args=[ex.id, symbol, tf], id=f"ohlcv:{ex.id}:{symbol}:{tf}")
                self._scheduler.add_job(self._collect_ticker, IntervalTrigger(seconds=10),
                                       args=[ex.id, symbol], id=f"ticker:{ex.id}:{symbol}")
        self._scheduler.start()
        logger.info("scheduler_started")
    
    def stop(self):
        self._scheduler.shutdown()
```

## Database Migration

### Alembic 配置

```ini
# alembic.ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+asyncpg://user:pass@localhost:5432/marketdata
```

### 初始迁移

```python
# alembic/versions/001_initial.py
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None

def upgrade():
    op.create_table('ohlcv',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('timeframe', sa.String(8), nullable=False),
        sa.Column('timestamp', sa.BigInteger(), nullable=False),
        sa.Column('open', sa.Numeric(18, 8), nullable=False),
        sa.Column('high', sa.Numeric(18, 8), nullable=False),
        sa.Column('low', sa.Numeric(18, 8), nullable=False),
        sa.Column('close', sa.Numeric(18, 8), nullable=False),
        sa.Column('volume', sa.Numeric(18, 4), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('exchange', 'symbol', 'timeframe', 'timestamp', name='uq_ohlcv_key'),
    )
    op.create_index('idx_ohlcv_lookup', 'ohlcv', ['exchange', 'symbol', 'timeframe', 'timestamp'])

def downgrade():
    op.drop_index('idx_ohlcv_lookup')
    op.drop_table('ohlcv')
```

## Error Handling

### API错误响应格式

```json
{
  "error": {
    "code": "INVALID_SYMBOL",
    "message": "Symbol 'XXX/USDT' is not supported",
    "details": {"symbol": "XXX/USDT", "exchange": "binance"}
  }
}
```

## Testing Strategy

### 测试架构

| 类型 | 工具 | 覆盖范围 | 说明 |
|------|------|----------|------|
| 单元测试 | pytest | 模型、工具函数、验证逻辑 | 快速、隔离 |
| 集成测试 | pytest + testcontainers | Repository、API、缓存 | 真实数据库/Redis |
| 属性测试 | hypothesis | 序列化/反序列化、数据完整性 | 随机输入验证 |
| E2E测试 | pytest + httpx | 完整 API 流程 | 端到端验证 |

### 测试目录结构

```
tests/
├── conftest.py              # 共享 fixtures
├── unit/
│   ├── test_models.py       # 模型单元测试
│   ├── test_config.py       # 配置验证测试
│   └── test_exceptions.py   # 异常测试
├── integration/
│   ├── test_repository.py   # Repository 集成测试
│   ├── test_cache.py        # 缓存集成测试
│   └── test_api.py          # API 集成测试
├── property/
│   ├── test_serialization.py # 序列化属性测试
│   ├── test_repository.py    # Repository 属性测试
│   └── strategies.py         # Hypothesis 策略
└── e2e/
    └── test_flows.py         # 端到端流程测试
```

### 测试 Fixtures

```python
# tests/conftest.py
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from httpx import AsyncClient, ASGITransport

from src.models import Base
from src.infrastructure.database import Database
from src.infrastructure.cache import Cache
from src.repositories import OHLCVRepository, TickerRepository
from src.main import app

# PostgreSQL 容器
@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:15") as postgres:
        yield postgres

# Redis 容器
@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:7") as redis:
        yield redis

# 数据库引擎
@pytest_asyncio.fixture
async def db_engine(postgres_container):
    url = postgres_container.get_connection_url().replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

# 数据库会话
@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

# 缓存
@pytest_asyncio.fixture
async def cache(redis_container):
    url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}"
    cache = Cache(url)
    await cache.connect()
    yield cache
    await cache.disconnect()

# Repository
@pytest_asyncio.fixture
async def ohlcv_repo(cache):
    return OHLCVRepository(cache)

# API 客户端
@pytest_asyncio.fixture
async def api_client(db_engine, cache):
    # 设置 app.state
    app.state.db = Database.__new__(Database)
    app.state.db.engine = db_engine
    app.state.db.session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    app.state.cache = cache
    app.state.clients = {}
    app.state.ohlcv_repo = OHLCVRepository(cache)
    app.state.ticker_repo = TickerRepository(cache, {})
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
```

### Hypothesis 策略

```python
# tests/property/strategies.py
from hypothesis import strategies as st
from decimal import Decimal
from src.models import OHLCV, Ticker

# OHLCV 生成策略
@st.composite
def ohlcv_strategy(draw):
    exchange = draw(st.sampled_from(["binance", "okx", "bybit"]))
    symbol = draw(st.sampled_from(["BTC/USDT", "ETH/USDT", "SOL/USDT"]))
    timeframe = draw(st.sampled_from(["1m", "5m", "15m", "1h", "4h", "1d"]))
    timestamp = draw(st.integers(min_value=1600000000000, max_value=1800000000000))
    
    # 确保 OHLCV 数据合理：low <= open/close <= high
    low = draw(st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=8))
    high = draw(st.decimals(min_value=low, max_value=low * 2, places=8))
    open_price = draw(st.decimals(min_value=low, max_value=high, places=8))
    close_price = draw(st.decimals(min_value=low, max_value=high, places=8))
    volume = draw(st.decimals(min_value=Decimal("0"), max_value=Decimal("1000000"), places=4))
    
    return OHLCV(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close_price,
        volume=volume,
    )

# Ticker 生成策略
@st.composite
def ticker_strategy(draw):
    exchange = draw(st.sampled_from(["binance", "okx", "bybit"]))
    symbol = draw(st.sampled_from(["BTC/USDT", "ETH/USDT", "SOL/USDT"]))
    last = draw(st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=8))
    timestamp = draw(st.integers(min_value=1600000000000, max_value=1800000000000))
    
    return Ticker(
        exchange=exchange,
        symbol=symbol,
        last=last,
        bid=draw(st.decimals(min_value=Decimal("0.01"), max_value=last, places=8) | st.none()),
        ask=draw(st.decimals(min_value=last, max_value=last * Decimal("1.1"), places=8) | st.none()),
        high_24h=draw(st.decimals(min_value=last, max_value=last * 2, places=8) | st.none()),
        low_24h=draw(st.decimals(min_value=Decimal("0.01"), max_value=last, places=8) | st.none()),
        volume_24h=draw(st.decimals(min_value=Decimal("0"), max_value=Decimal("1000000"), places=4) | st.none()),
        change_pct_24h=draw(st.decimals(min_value=Decimal("-100"), max_value=Decimal("1000"), places=2) | st.none()),
        timestamp=timestamp,
    )

# 时间范围策略
@st.composite
def time_range_strategy(draw):
    start = draw(st.integers(min_value=1600000000000, max_value=1700000000000))
    end = draw(st.integers(min_value=start, max_value=start + 86400000 * 30))  # 最多30天
    return start, end
```

### 单元测试示例

```python
# tests/unit/test_models.py
import pytest
from decimal import Decimal
from src.models import OHLCV, Ticker

class TestOHLCV:
    def test_to_dict_preserves_precision(self):
        ohlcv = OHLCV(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=1700000000000,
            open=Decimal("43250.12345678"),
            high=Decimal("43500.00000000"),
            low=Decimal("43100.00000000"),
            close=Decimal("43350.25000000"),
            volume=Decimal("1234.5678"),
        )
        d = ohlcv.to_dict()
        assert d["open"] == "43250.12345678"
        assert d["volume"] == "1234.5678"
    
    def test_from_dict_creates_equivalent(self):
        original = OHLCV(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=1700000000000,
            open=Decimal("43250.50"),
            high=Decimal("43500.00"),
            low=Decimal("43100.00"),
            close=Decimal("43350.25"),
            volume=Decimal("1234.5678"),
        )
        restored = OHLCV.from_dict(original.to_dict())
        assert restored.exchange == original.exchange
        assert restored.open == original.open

class TestTicker:
    def test_optional_fields_none(self):
        ticker = Ticker(
            exchange="binance",
            symbol="BTC/USDT",
            last=Decimal("43350.25"),
            timestamp=1700000000000,
        )
        d = ticker.to_dict()
        assert d["bid"] is None
        assert d["ask"] is None
```

### 集成测试示例

```python
# tests/integration/test_repository.py
import pytest
from decimal import Decimal
from src.models import OHLCV

@pytest.mark.asyncio
async def test_save_and_find(db_session, ohlcv_repo):
    """测试保存和查询"""
    records = [
        OHLCV(exchange="binance", symbol="BTC/USDT", timeframe="1h",
              timestamp=1700000000000 + i * 3600000,
              open=Decimal("43250"), high=Decimal("43500"),
              low=Decimal("43100"), close=Decimal("43350"), volume=Decimal("1234"))
        for i in range(10)
    ]
    
    await ohlcv_repo.save(db_session, records)
    await db_session.commit()
    
    results, cursor, cached = await ohlcv_repo.find(
        db_session, "binance", "BTC/USDT", "1h", limit=5
    )
    
    assert len(results) == 5
    assert cursor is not None
    assert not cached

@pytest.mark.asyncio
async def test_upsert_updates_existing(db_session, ohlcv_repo):
    """测试 upsert 更新已存在的记录"""
    original = OHLCV(
        exchange="binance", symbol="BTC/USDT", timeframe="1h",
        timestamp=1700000000000,
        open=Decimal("43250"), high=Decimal("43500"),
        low=Decimal("43100"), close=Decimal("43350"), volume=Decimal("1234")
    )
    await ohlcv_repo.save(db_session, [original])
    await db_session.commit()
    
    # 更新同一条记录
    updated = OHLCV(
        exchange="binance", symbol="BTC/USDT", timeframe="1h",
        timestamp=1700000000000,
        open=Decimal("43300"), high=Decimal("43600"),
        low=Decimal("43200"), close=Decimal("43400"), volume=Decimal("2000")
    )
    await ohlcv_repo.save(db_session, [updated])
    await db_session.commit()
    
    results, _, _ = await ohlcv_repo.find(
        db_session, "binance", "BTC/USDT", "1h",
        start=1700000000000, end=1700000000000
    )
    
    assert len(results) == 1
    assert results[0].close == Decimal("43400")
    assert results[0].volume == Decimal("2000")
```

### API 集成测试示例

```python
# tests/integration/test_api.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_get_ohlcv_empty(api_client: AsyncClient):
    """测试查询空数据"""
    response = await api_client.get(
        "/api/v1/ohlcv/binance/BTC%2FUSDT",
        params={"timeframe": "1h"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data"] == []
    assert "meta" in data

@pytest.mark.asyncio
async def test_get_ohlcv_invalid_timeframe(api_client: AsyncClient):
    """测试无效的 timeframe"""
    response = await api_client.get(
        "/api/v1/ohlcv/binance/BTC%2FUSDT",
        params={"timeframe": "invalid"}
    )
    assert response.status_code == 422  # Validation error

@pytest.mark.asyncio
async def test_batch_exceeds_limit(api_client: AsyncClient):
    """测试批量查询超过限制"""
    response = await api_client.post(
        "/api/v1/ohlcv/batch",
        json={
            "exchange": "binance",
            "symbols": [f"SYMBOL{i}/USDT" for i in range(25)],
            "timeframe": "1h"
        }
    )
    assert response.status_code == 400
    assert "BATCH_SIZE_EXCEEDED" in response.text

@pytest.mark.asyncio
async def test_health_check(api_client: AsyncClient):
    """测试健康检查"""
    response = await api_client.get("/health")
    assert response.status_code in [200, 503]
    data = response.json()
    assert "status" in data
    assert "components" in data
```


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system.*

### Property 1: OHLCV Serialization Round-Trip

*For any* valid OHLCV object, `OHLCV.from_dict(ohlcv.to_dict())` SHALL produce an equivalent object.

**Validates: Requirements 1.6**

```python
@given(ohlcv=ohlcv_strategy())
@settings(max_examples=100)
def test_ohlcv_roundtrip(ohlcv: OHLCV):
    assert OHLCV.from_dict(ohlcv.to_dict()) == ohlcv
```

### Property 2: Ticker Serialization Round-Trip

*For any* valid Ticker object, `Ticker.from_dict(ticker.to_dict())` SHALL produce an equivalent object.

**Validates: Requirements 2.4**

```python
@given(ticker=ticker_strategy())
@settings(max_examples=100)
def test_ticker_roundtrip(ticker: Ticker):
    assert Ticker.from_dict(ticker.to_dict()) == ticker
```

### Property 3: Upsert Idempotence

*For any* OHLCV record, saving it multiple times SHALL result in exactly one record in the database.

**Validates: Requirements 8.1, 8.2**

```python
@given(ohlcv=ohlcv_strategy())
@settings(max_examples=100)
async def test_upsert_idempotence(repo: OHLCVRepository, ohlcv: OHLCV):
    await repo.save([ohlcv])
    await repo.save([ohlcv])
    records, _, _ = await repo.find(ohlcv.exchange, ohlcv.symbol, ohlcv.timeframe,
                                    start=ohlcv.timestamp, end=ohlcv.timestamp)
    assert len(records) == 1
```

### Property 4: Pagination Completeness

*For any* dataset, iterating through all pages SHALL return all records exactly once.

**Validates: Requirements 1.2**

```python
@given(records=st.lists(ohlcv_strategy(), min_size=50, max_size=200))
@settings(max_examples=50)
async def test_pagination(repo: OHLCVRepository, records: List[OHLCV]):
    # Normalize records
    for i, r in enumerate(records):
        r.exchange, r.symbol, r.timeframe = "binance", "BTC/USDT", "1h"
        r.timestamp = 1700000000000 + i * 60000
    
    await repo.save(records)
    
    all_results, cursor = [], None
    while True:
        page, cursor, _ = await repo.find("binance", "BTC/USDT", "1h", limit=20, cursor=cursor)
        all_results.extend(page)
        if not cursor:
            break
    
    assert len(all_results) == len(records)
```

### Property 5: Query Filtering Correctness

*For any* query with time range, all returned records SHALL have timestamps within range.

**Validates: Requirements 1.1**

```python
@given(records=st.lists(ohlcv_strategy(), min_size=10, max_size=100))
@settings(max_examples=100)
async def test_filtering(repo: OHLCVRepository, records: List[OHLCV]):
    for i, r in enumerate(records):
        r.exchange, r.symbol, r.timeframe = "binance", "BTC/USDT", "1h"
        r.timestamp = 1700000000000 + i * 60000
    
    await repo.save(records)
    timestamps = sorted(r.timestamp for r in records)
    start, end = timestamps[len(timestamps)//4], timestamps[3*len(timestamps)//4]
    
    results, _, _ = await repo.find("binance", "BTC/USDT", "1h", start=start, end=end)
    for r in results:
        assert start <= r.timestamp <= end
```

### Property 6: Batch Partial Failure

*For any* batch request with mixed valid/invalid symbols, response SHALL contain both data and errors.

**Validates: Requirements 3.2**

```python
@given(valid=st.lists(st.sampled_from(["BTC/USDT", "ETH/USDT"]), min_size=1, max_size=5),
       invalid=st.lists(st.text(min_size=3, max_size=10), min_size=1, max_size=3))
@settings(max_examples=50)
async def test_batch_partial(client, valid, invalid):
    resp = await client.post("/api/v1/ohlcv/batch", json={"symbols": valid + invalid, "timeframe": "1h"})
    data = resp.json()
    assert "data" in data and "errors" in data
```

### Property 7: Cache Size Limit

*For any* sequence of OHLCV writes, cache SHALL contain at most the configured limit.

**Validates: Requirements 8.3**

```python
@given(records=st.lists(ohlcv_strategy(), min_size=600, max_size=1000))
@settings(max_examples=50)
async def test_cache_limit(cache: Cache, records: List[OHLCV]):
    for r in records:
        r.exchange, r.symbol, r.timeframe = "binance", "BTC/USDT", "1h"
    await cache.cache_ohlcv(records)
    cached = await cache.get_ohlcv("binance", "BTC/USDT", "1h")
    assert len(cached) <= cache.ohlcv_cache_size
```

### Property 8: Health Status Mapping

*For any* component health combination, overall status SHALL be correct.

**Validates: Requirements 7.1, 7.2**

```python
@given(pg_ok=st.booleans(), redis_ok=st.booleans())
def test_health_status(pg_ok, redis_ok):
    status = compute_health(pg_ok, redis_ok)
    if pg_ok and redis_ok:
        assert status == "healthy"
    else:
        assert status == "degraded"
```
