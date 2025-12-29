"""Dependency injection module for Crypto Market Data Service.

Provides FastAPI dependencies for:
- Database and session management
- Cache access
- Exchange clients
- Repositories
- Request validation

Uses app.state + Request pattern for dependency injection.

Requirements: 1.3, 2.2
"""

from typing import Annotated, AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import ClientError, ErrorCode
from src.infrastructure.cache import Cache
from src.infrastructure.database import Database
from src.infrastructure.exchange import ExchangeClient
from src.infrastructure.scheduler import CollectionScheduler
from src.repositories import OHLCVRepository, TickerRepository


# ==================== Infrastructure Dependencies ====================
# These retrieve components from app.state (initialized in lifespan)


def get_db(request: Request) -> Database:
    """获取数据库实例.
    
    从 app.state 获取在 lifespan 中初始化的 Database 实例。
    
    Args:
        request: FastAPI Request 对象
        
    Returns:
        Database 实例
    """
    return request.app.state.db


def get_cache(request: Request) -> Cache:
    """获取缓存实例.
    
    从 app.state 获取在 lifespan 中初始化的 Cache 实例。
    
    Args:
        request: FastAPI Request 对象
        
    Returns:
        Cache 实例
    """
    return request.app.state.cache


def get_exchange_clients(request: Request) -> dict[str, ExchangeClient]:
    """获取交易所客户端字典.
    
    从 app.state 获取在 lifespan 中初始化的交易所客户端。
    
    Args:
        request: FastAPI Request 对象
        
    Returns:
        交易所客户端字典 {exchange_id: ExchangeClient}
    """
    return request.app.state.clients


def get_ohlcv_repo(request: Request) -> OHLCVRepository:
    """获取 OHLCV Repository.
    
    从 app.state 获取在 lifespan 中初始化的 OHLCVRepository。
    
    Args:
        request: FastAPI Request 对象
        
    Returns:
        OHLCVRepository 实例
    """
    return request.app.state.ohlcv_repo


def get_ticker_repo(request: Request) -> TickerRepository:
    """获取 Ticker Repository.
    
    从 app.state 获取在 lifespan 中初始化的 TickerRepository。
    
    Args:
        request: FastAPI Request 对象
        
    Returns:
        TickerRepository 实例
    """
    return request.app.state.ticker_repo


def get_scheduler(request: Request) -> CollectionScheduler | None:
    """获取调度器实例.
    
    从 app.state 获取在 lifespan 中初始化的 CollectionScheduler。
    
    Args:
        request: FastAPI Request 对象
        
    Returns:
        CollectionScheduler 实例，如果未启动则返回 None
    """
    return getattr(request.app.state, 'scheduler', None)


# ==================== Session Dependency ====================


async def get_db_session(
    db: Annotated[Database, Depends(get_db)]
) -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话（带自动提交/回滚）.
    
    核心依赖注入：每个请求一个会话。
    - 请求结束自动提交或回滚
    - 支持跨 Repository 事务
    
    Args:
        db: Database 实例（通过依赖注入）
        
    Yields:
        AsyncSession: 数据库会话
        
    Example:
        ```python
        @router.get("/data")
        async def get_data(session: DbSession):
            result = await session.execute(select(Model))
            return result.scalars().all()
        ```
    """
    async with db.session() as session:
        yield session


# ==================== Validation Dependencies ====================


def validate_exchange(
    exchange: str,
    clients: Annotated[dict[str, ExchangeClient], Depends(get_exchange_clients)],
) -> str:
    """验证交易所是否在配置中.
    
    检查请求的交易所是否已配置并可用。
    
    Args:
        exchange: 交易所 ID (binance, okx 等)
        clients: 交易所客户端字典（通过依赖注入）
        
    Returns:
        验证通过的交易所 ID
        
    Raises:
        ClientError: 交易所未配置或不可用
    """
    if exchange not in clients:
        raise ClientError(
            ErrorCode.INVALID_EXCHANGE,
            f"Unknown exchange: {exchange}",
            {"exchange": exchange, "available_exchanges": list(clients.keys())},
        )
    return exchange


def validate_symbol(symbol: str) -> str:
    """验证交易对格式.
    
    检查交易对是否符合 BASE/QUOTE 格式。
    
    Args:
        symbol: 交易对 (BTC/USDT, ETH/USDT 等)
        
    Returns:
        验证通过的交易对
        
    Raises:
        ClientError: 交易对格式无效
    """
    if "/" not in symbol:
        raise ClientError(
            ErrorCode.INVALID_SYMBOL,
            f"Invalid symbol format: {symbol}. Expected format: BASE/QUOTE",
            {"symbol": symbol, "expected_format": "BASE/QUOTE"},
        )
    
    parts = symbol.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ClientError(
            ErrorCode.INVALID_SYMBOL,
            f"Invalid symbol format: {symbol}. Expected format: BASE/QUOTE",
            {"symbol": symbol, "expected_format": "BASE/QUOTE"},
        )
    
    return symbol


# 有效的时间周期
VALID_TIMEFRAMES = {
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M"
}


def validate_timeframe(timeframe: str) -> str:
    """验证时间周期.
    
    检查时间周期是否在支持的列表中。
    
    Args:
        timeframe: K线周期 (1m, 5m, 1h, 1d 等)
        
    Returns:
        验证通过的时间周期
        
    Raises:
        ClientError: 时间周期无效
    """
    if timeframe not in VALID_TIMEFRAMES:
        raise ClientError(
            ErrorCode.INVALID_TIMEFRAME,
            f"Invalid timeframe: {timeframe}",
            {"timeframe": timeframe, "valid_timeframes": sorted(VALID_TIMEFRAMES)},
        )
    return timeframe


# ==================== Type Aliases ====================
# Simplify route function signatures


# Infrastructure dependencies
DbDep = Annotated[Database, Depends(get_db)]
CacheDep = Annotated[Cache, Depends(get_cache)]
ExchangeClients = Annotated[dict[str, ExchangeClient], Depends(get_exchange_clients)]

# Session dependency (core)
DbSession = Annotated[AsyncSession, Depends(get_db_session)]

# Repository dependencies
OHLCVRepo = Annotated[OHLCVRepository, Depends(get_ohlcv_repo)]
TickerRepo = Annotated[TickerRepository, Depends(get_ticker_repo)]

# Validation dependencies
ValidExchange = Annotated[str, Depends(validate_exchange)]
ValidSymbol = Annotated[str, Depends(validate_symbol)]
ValidTimeframe = Annotated[str, Depends(validate_timeframe)]
