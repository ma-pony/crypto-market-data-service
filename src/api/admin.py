"""Admin API endpoints for Crypto Market Data Service.

Provides administrative operations:
- Manual gap filling trigger
- Scheduler control
- System maintenance

Requirements: 4.5
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.dependencies import get_scheduler


logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class GapFillRequest(BaseModel):
    """Gap filling request model."""
    
    exchange: str = Field(..., description="交易所 ID (binance, okx, gateio)")
    symbol: str = Field(..., description="交易对 (BTC/USDT, ETH/USDT)")
    timeframe: str = Field(..., description="K线周期 (1m, 5m, 15m, 1h, 4h, 1d)")
    days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="补全天数 (1-365天，默认30天)",
    )


class GapFillResponse(BaseModel):
    """Gap filling response model."""
    
    status: str = Field(..., description="状态 (started, already_running)")
    message: str = Field(..., description="消息")
    exchange: str = Field(..., description="交易所 ID")
    symbol: str = Field(..., description="交易对")
    timeframe: str = Field(..., description="K线周期")
    days: int = Field(..., description="补全天数")


@router.post("/gap-fill", response_model=GapFillResponse)
async def trigger_gap_fill(
    request: GapFillRequest,
    scheduler = Depends(get_scheduler),
) -> GapFillResponse:
    """手动触发历史数据补全.
    
    此接口允许手动触发指定交易所、交易对和时间周期的历史数据补全。
    
    Args:
        request: Gap filling 请求参数
        scheduler: 调度器实例（依赖注入）
        
    Returns:
        GapFillResponse: 补全任务状态
        
    Raises:
        HTTPException: 如果调度器未运行或参数无效
        
    Example:
        ```bash
        curl -X POST "http://localhost:8000/api/v1/admin/gap-fill" \\
             -H "Content-Type: application/json" \\
             -d '{
                   "exchange": "binance",
                   "symbol": "BTC/USDT",
                   "timeframe": "1d",
                   "days": 90
                 }'
        ```
    """
    if not scheduler:
        raise HTTPException(
            status_code=503,
            detail="Scheduler is not running",
        )
    
    # 验证交易所是否存在
    if request.exchange not in scheduler.clients:
        raise HTTPException(
            status_code=400,
            detail=f"Exchange '{request.exchange}' not configured",
        )
    
    # 验证时间周期是否支持
    if request.timeframe not in scheduler.TIMEFRAME_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"Timeframe '{request.timeframe}' not supported",
        )
    
    # 触发 gap filling（异步执行）
    import asyncio
    asyncio.create_task(
        scheduler._fill_ohlcv_gap(
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            gap_days=request.days,
        )
    )
    
    logger.info(
        "gap_fill_triggered",
        exchange=request.exchange,
        symbol=request.symbol,
        timeframe=request.timeframe,
        days=request.days,
    )
    
    return GapFillResponse(
        status="started",
        message=f"Gap filling started for {request.exchange}/{request.symbol}/{request.timeframe}",
        exchange=request.exchange,
        symbol=request.symbol,
        timeframe=request.timeframe,
        days=request.days,
    )


class BatchGapFillRequest(BaseModel):
    """Batch gap filling request model."""
    
    days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="补全天数 (1-365天，默认30天)",
    )
    exchanges: Optional[list[str]] = Field(
        default=None,
        description="指定交易所列表，为空则补全所有配置的交易所",
    )
    timeframes: Optional[list[str]] = Field(
        default=None,
        description="指定时间周期列表，为空则补全所有配置的时间周期",
    )


class BatchGapFillResponse(BaseModel):
    """Batch gap filling response model."""
    
    status: str = Field(..., description="状态")
    message: str = Field(..., description="消息")
    total_tasks: int = Field(..., description="总任务数")
    days: int = Field(..., description="补全天数")


@router.post("/gap-fill/batch", response_model=BatchGapFillResponse)
async def trigger_batch_gap_fill(
    request: BatchGapFillRequest,
    scheduler = Depends(get_scheduler),
) -> BatchGapFillResponse:
    """批量触发历史数据补全.
    
    此接口允许批量触发多个交易所、交易对和时间周期的历史数据补全。
    
    Args:
        request: 批量 gap filling 请求参数
        scheduler: 调度器实例（依赖注入）
        
    Returns:
        BatchGapFillResponse: 批量补全任务状态
        
    Raises:
        HTTPException: 如果调度器未运行
        
    Example:
        ```bash
        # 补全所有配置的交易所和时间周期（90天）
        curl -X POST "http://localhost:8000/api/v1/admin/gap-fill/batch" \\
             -H "Content-Type: application/json" \\
             -d '{"days": 90}'
        
        # 只补全指定交易所的1日线数据（90天）
        curl -X POST "http://localhost:8000/api/v1/admin/gap-fill/batch" \\
             -H "Content-Type: application/json" \\
             -d '{
                   "days": 90,
                   "exchanges": ["binance", "okx"],
                   "timeframes": ["1d"]
                 }'
        ```
    """
    if not scheduler:
        raise HTTPException(
            status_code=503,
            detail="Scheduler is not running",
        )
    
    # 获取配置
    from src.config import get_settings
    settings = get_settings()
    
    # 确定要补全的交易所
    target_exchanges = request.exchanges if request.exchanges else [ex.id for ex in settings.exchanges]
    
    # 确定要补全的时间周期
    target_timeframes = request.timeframes if request.timeframes else settings.timeframes
    
    # 触发批量 gap filling
    import asyncio
    task_count = 0
    
    for exchange_id in target_exchanges:
        # 验证交易所是否存在
        if exchange_id not in scheduler.clients:
            logger.warning(
                "exchange_not_configured",
                exchange=exchange_id,
            )
            continue
        
        # 获取该交易所的交易对
        exchange_config = next((ex for ex in settings.exchanges if ex.id == exchange_id), None)
        if not exchange_config:
            continue
        
        for symbol in exchange_config.symbols:
            for timeframe in target_timeframes:
                # 验证时间周期是否支持
                if timeframe not in scheduler.TIMEFRAME_SECONDS:
                    logger.warning(
                        "timeframe_not_supported",
                        timeframe=timeframe,
                    )
                    continue
                
                # 触发 gap filling（异步执行）
                asyncio.create_task(
                    scheduler._fill_ohlcv_gap(
                        exchange=exchange_id,
                        symbol=symbol,
                        timeframe=timeframe,
                        gap_days=request.days,
                    )
                )
                task_count += 1
    
    logger.info(
        "batch_gap_fill_triggered",
        total_tasks=task_count,
        days=request.days,
        exchanges=target_exchanges,
        timeframes=target_timeframes,
    )
    
    return BatchGapFillResponse(
        status="started",
        message=f"Batch gap filling started for {task_count} tasks",
        total_tasks=task_count,
        days=request.days,
    )
