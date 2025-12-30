"""OHLCV API routes for Crypto Market Data Service.

Provides endpoints for querying K-line (OHLCV) data:
- GET /api/v1/ohlcv/{exchange}/{symbol}: Query OHLCV data with pagination
- POST /api/v1/ohlcv/batch: Batch query multiple symbols

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.1, 3.2, 3.3, 3.4
"""

import time
from typing import Annotated, Optional

from fastapi import APIRouter, Query

from src.api.schemas import (
    BatchErrorItem,
    BatchRequest,
    BatchResponse,
    OHLCVListMeta,
    OHLCVListResponse,
    OHLCVResponse,
    PaginationInfo,
)
from src.auth import AuthToken
from src.dependencies import (
    DbSession,
    OHLCVRepo,
    ValidExchange,
    ValidTimeframe,
    VALID_TIMEFRAMES,
)
from src.exceptions import ClientError, ErrorCode

router = APIRouter(prefix="/api/v1", tags=["OHLCV"])

# Maximum time range in milliseconds (30 days)
MAX_TIME_RANGE_MS = 30 * 24 * 60 * 60 * 1000


def _validate_time_range(start: Optional[int], end: Optional[int]) -> None:
    """Validate that time range does not exceed 30 days.
    
    Args:
        start: Start timestamp in milliseconds
        end: End timestamp in milliseconds
        
    Raises:
        ClientError: If time range exceeds 30 days
    """
    if start is not None and end is not None:
        if end < start:
            raise ClientError(
                ErrorCode.INVALID_TIME_RANGE,
                "End timestamp must be greater than or equal to start timestamp",
                {"start": start, "end": end},
            )
        if end - start > MAX_TIME_RANGE_MS:
            raise ClientError(
                ErrorCode.INVALID_TIME_RANGE,
                "Time range exceeds maximum of 30 days",
                {
                    "start": start,
                    "end": end,
                    "range_days": (end - start) / (24 * 60 * 60 * 1000),
                    "max_days": 30,
                },
            )


def _validate_symbol(symbol: str) -> str:
    """Validate symbol format (BASE/QUOTE).
    
    Args:
        symbol: Trading pair symbol
        
    Returns:
        Validated symbol
        
    Raises:
        ClientError: If symbol format is invalid
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


@router.get("/ohlcv/{exchange}/{symbol:path}", response_model=OHLCVListResponse)
async def get_ohlcv(
    token: AuthToken,  # 认证依赖
    exchange: ValidExchange,
    symbol: str,
    session: DbSession,
    ohlcv_repo: OHLCVRepo,
    timeframe: Annotated[
        str,
        Query(
            description="K-line timeframe",
            pattern="^(1m|3m|5m|15m|30m|1h|2h|4h|6h|8h|12h|1d|3d|1w|1M)$",
        ),
    ],
    start: Annotated[
        Optional[int],
        Query(description="Start timestamp in milliseconds"),
    ] = None,
    end: Annotated[
        Optional[int],
        Query(description="End timestamp in milliseconds"),
    ] = None,
    limit: Annotated[
        int,
        Query(le=1000, ge=1, description="Maximum number of records to return"),
    ] = 500,
    cursor: Annotated[
        Optional[str],
        Query(description="Pagination cursor from previous response"),
    ] = None,
) -> OHLCVListResponse:
    """Query OHLCV (K-line) data for a specific exchange and symbol.
    
    Returns historical K-line data with support for:
    - Time range filtering (start/end timestamps)
    - Cursor-based pagination for large datasets
    - Cache-first strategy for fast responses
    
    Args:
        exchange: Exchange ID (e.g., binance, okx)
        symbol: Trading pair (e.g., BTC/USDT)
        session: Database session (injected)
        ohlcv_repo: OHLCV repository (injected)
        timeframe: K-line timeframe (1m, 5m, 1h, etc.)
        start: Start timestamp in milliseconds (optional)
        end: End timestamp in milliseconds (optional)
        limit: Maximum records to return (1-1000, default 500)
        cursor: Pagination cursor from previous response
        
    Returns:
        OHLCVListResponse with data, pagination info, and metadata
        
    Raises:
        ClientError: Invalid exchange, symbol, timeframe, or time range
        
    Example:
        GET /api/v1/ohlcv/binance/BTC%2FUSDT?timeframe=1h&limit=100
    """
    t0 = time.time()
    
    # Validate symbol format
    _validate_symbol(symbol)
    
    # Validate timeframe
    if timeframe not in VALID_TIMEFRAMES:
        raise ClientError(
            ErrorCode.INVALID_TIMEFRAME,
            f"Invalid timeframe: {timeframe}",
            {"timeframe": timeframe, "valid_timeframes": sorted(VALID_TIMEFRAMES)},
        )
    
    # Validate time range (max 30 days)
    _validate_time_range(start, end)
    
    # Query data
    records, next_cursor, cached = await ohlcv_repo.find(
        session=session,
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        limit=limit,
        cursor=cursor,
    )
    
    # Calculate query time
    query_ms = int((time.time() - t0) * 1000)
    
    return OHLCVListResponse(
        data=[OHLCVResponse(**r.to_dict()) for r in records],
        pagination=PaginationInfo(next_cursor=next_cursor),
        meta=OHLCVListMeta(cached=cached, query_ms=query_ms),
    )


@router.post("/ohlcv/batch", response_model=BatchResponse)
async def batch_ohlcv(
    token: AuthToken,  # 认证依赖
    request: BatchRequest,
    session: DbSession,
    ohlcv_repo: OHLCVRepo,
) -> BatchResponse:
    """Batch query OHLCV data for multiple symbols.
    
    Allows querying multiple trading pairs in a single request.
    Returns partial results if some symbols fail.
    
    Args:
        request: Batch request with exchange, symbols, timeframe, and time range
        session: Database session (injected)
        ohlcv_repo: OHLCV repository (injected)
        
    Returns:
        BatchResponse with data for each symbol and any errors
        
    Raises:
        ClientError: If symbols count exceeds 20 or invalid parameters
        
    Example:
        POST /api/v1/ohlcv/batch
        {
            "exchange": "binance",
            "symbols": ["BTC/USDT", "ETH/USDT"],
            "timeframe": "1h",
            "start": 1703404800000,
            "end": 1703491200000
        }
    """
    # Validate batch size (already validated by Pydantic max_length=20)
    if len(request.symbols) > 20:
        raise ClientError(
            ErrorCode.BATCH_SIZE_EXCEEDED,
            "Maximum 20 symbols per batch request",
            {"requested": len(request.symbols), "maximum": 20},
        )
    
    # Validate timeframe
    if request.timeframe not in VALID_TIMEFRAMES:
        raise ClientError(
            ErrorCode.INVALID_TIMEFRAME,
            f"Invalid timeframe: {request.timeframe}",
            {"timeframe": request.timeframe, "valid_timeframes": sorted(VALID_TIMEFRAMES)},
        )
    
    # Validate time range
    _validate_time_range(request.start, request.end)
    
    data: dict[str, list[OHLCVResponse]] = {}
    errors: list[BatchErrorItem] = []
    
    for symbol in request.symbols:
        try:
            # Validate symbol format
            _validate_symbol(symbol)
            
            # Query data for this symbol
            records, _, _ = await ohlcv_repo.find(
                session=session,
                exchange=request.exchange,
                symbol=symbol,
                timeframe=request.timeframe,
                start=request.start,
                end=request.end,
                limit=1000,  # Use max limit for batch
            )
            
            data[symbol] = [OHLCVResponse(**r.to_dict()) for r in records]
            
        except ClientError as e:
            errors.append(BatchErrorItem(symbol=symbol, error=e.message))
        except Exception as e:
            errors.append(BatchErrorItem(symbol=symbol, error=str(e)))
    
    return BatchResponse(data=data, errors=errors)
