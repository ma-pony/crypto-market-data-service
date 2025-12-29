"""Application entry point for Crypto Market Data Service.

Implements FastAPI application with:
- Lifespan context manager for startup/shutdown
- Component initialization to app.state
- Route registration
- Global exception handlers
- Request correlation ID tracking

Requirements: 4.1, 6.1
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging

import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from asgi_correlation_id.context import correlation_id
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.admin import router as admin_router
from src.api.health import router as health_router
from src.api.ohlcv import router as ohlcv_router
from src.api.ticker import router as ticker_router
from src.config import get_settings
from src.exceptions import ClientError, MarketDataError, RateLimitError
from src.infrastructure.cache import Cache
from src.infrastructure.database import Database
from src.infrastructure.exchange import ExchangeClient
from src.infrastructure.scheduler import CollectionScheduler
from src.repositories import OHLCVRepository, TickerRepository


# ==================== Configure Structlog with Correlation ID ====================

def add_correlation_id(logger, method_name, event_dict):
    """Add correlation ID to log records."""
    if cid := correlation_id.get():
        event_dict["correlation_id"] = cid
    return event_dict


structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        add_correlation_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理.
    
    使用 app.state 存储依赖，在启动时初始化所有组件，
    在关闭时清理资源。
    
    Startup:
        1. 加载配置
        2. 初始化数据库连接
        3. 初始化 Redis 缓存
        4. 初始化交易所客户端
        5. 初始化 Repository
    
    Shutdown:
        1. 关闭交易所客户端
        2. 关闭 Redis 连接
        3. 关闭数据库连接池
    
    Args:
        app: FastAPI 应用实例
        
    Yields:
        None: 应用运行期间
    """
    settings = get_settings()
    
    logger.info(
        "Starting Crypto Market Data Service",
        host=settings.api_host,
        port=settings.api_port,
    )
    
    # ==================== Startup ====================
    
    # 1. 初始化数据库
    logger.info("Initializing database connection", url=settings.database_url[:30] + "...")
    app.state.db = Database(
        url=settings.database_url,
        pool_size=settings.database_pool_size,
    )
    
    # 2. 初始化 Redis 缓存
    logger.info("Initializing Redis cache", url=settings.redis_url)
    app.state.cache = Cache(
        url=settings.redis_url,
        ohlcv_cache_size=settings.ohlcv_cache_size,
        ticker_ttl=settings.ticker_ttl_seconds,
    )
    await app.state.cache.connect()
    
    # 3. 初始化交易所客户端
    app.state.clients: dict[str, ExchangeClient] = {}
    for ex_config in settings.exchanges:
        logger.info("Initializing exchange client", exchange=ex_config.id)
        client = ExchangeClient(
            exchange_id=ex_config.id,
            api_key=ex_config.api_key,
            secret=ex_config.secret,
        )
        await client.connect()
        app.state.clients[ex_config.id] = client
    
    # 4. 初始化 Repository
    app.state.ohlcv_repo = OHLCVRepository(cache=app.state.cache)
    app.state.ticker_repo = TickerRepository(
        cache=app.state.cache,
        clients=app.state.clients,
    )
    
    # 5. 启动调度器（如果配置了交易所）
    if settings.exchanges:
        logger.info("Starting data collection scheduler")
        app.state.scheduler = CollectionScheduler(
            db=app.state.db,
            clients=app.state.clients,
            ohlcv_repo=app.state.ohlcv_repo,
            ticker_repo=app.state.ticker_repo,
        )
        app.state.scheduler.start(
            exchanges=settings.exchanges,
            timeframes=settings.timeframes,
            gap_fill_enabled=settings.gap_fill_enabled,
            gap_fill_days=settings.gap_fill_days,
        )
        logger.info(
            "Scheduler started",
            job_count=app.state.scheduler.get_job_count(),
            gap_fill_enabled=settings.gap_fill_enabled,
        )
    else:
        logger.warning("No exchanges configured, scheduler not started")
        app.state.scheduler = None
    
    logger.info(
        "Service started successfully",
        exchanges=list(app.state.clients.keys()),
    )
    
    yield  # 应用运行中
    
    # ==================== Shutdown ====================
    
    logger.info("Shutting down Crypto Market Data Service")
    
    # 1. 停止调度器
    if hasattr(app.state, 'scheduler') and app.state.scheduler:
        logger.info("Stopping data collection scheduler")
        app.state.scheduler.stop()
    
    # 2. 关闭交易所客户端
    for exchange_id, client in app.state.clients.items():
        logger.info("Closing exchange client", exchange=exchange_id)
        await client.disconnect()
    
    # 3. 关闭 Redis 连接
    logger.info("Closing Redis connection")
    await app.state.cache.disconnect()
    
    # 4. 关闭数据库连接池
    logger.info("Closing database connection pool")
    await app.state.db.dispose()
    
    logger.info("Service shutdown complete")


# ==================== Create Application ====================

app = FastAPI(
    title="Crypto Market Data Service",
    description="数字货币交易数据服务 - 为量化交易系统提供统一的市场数据访问能力",
    version="1.0.0",
    lifespan=lifespan,
)


# ==================== Add Middleware ====================

# Add correlation ID middleware
app.add_middleware(
    CorrelationIdMiddleware,
    header_name="X-Request-ID",
    update_request_header=True,
)


# ==================== Register Routes ====================

app.include_router(admin_router)
app.include_router(ohlcv_router)
app.include_router(ticker_router)
app.include_router(health_router)


# ==================== Exception Handlers ====================


@app.exception_handler(ClientError)
async def client_error_handler(request: Request, exc: ClientError) -> JSONResponse:
    """处理客户端错误 (4xx).
    
    Args:
        request: FastAPI Request 对象
        exc: ClientError 异常
        
    Returns:
        JSONResponse: 错误响应
    """
    logger.warning(
        "Client error",
        error_code=exc.code.value,
        message=exc.message,
        details=exc.details,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=400,
        content=exc.to_dict(),
    )


@app.exception_handler(RateLimitError)
async def rate_limit_error_handler(request: Request, exc: RateLimitError) -> JSONResponse:
    """处理速率限制错误.
    
    Args:
        request: FastAPI Request 对象
        exc: RateLimitError 异常
        
    Returns:
        JSONResponse: 错误响应，包含 Retry-After 头
    """
    logger.warning(
        "Rate limit exceeded",
        exchange=exc.exchange,
        retry_after=exc.retry_after,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=429,
        content=exc.to_dict(),
        headers={"Retry-After": str(exc.retry_after)},
    )


@app.exception_handler(MarketDataError)
async def market_data_error_handler(request: Request, exc: MarketDataError) -> JSONResponse:
    """处理服务端错误 (5xx).
    
    Args:
        request: FastAPI Request 对象
        exc: MarketDataError 异常
        
    Returns:
        JSONResponse: 错误响应
    """
    logger.error(
        "Server error",
        error_code=exc.code.value,
        message=exc.message,
        details=exc.details,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """处理未捕获的异常.
    
    Args:
        request: FastAPI Request 对象
        exc: 未捕获的异常
        
    Returns:
        JSONResponse: 通用错误响应
    """
    logger.exception(
        "Unhandled exception",
        error=str(exc),
        path=request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": {},
            }
        },
    )


# ==================== Root Endpoint ====================


@app.get("/")
async def root() -> dict:
    """根路径端点.
    
    Returns:
        服务信息
    """
    return {
        "service": "Crypto Market Data Service",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }
