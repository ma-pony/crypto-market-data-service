"""Ticker API routes for Crypto Market Data Service.

Provides endpoints for querying real-time ticker data:
- GET /api/v1/ticker/{exchange}/{symbol}: Query single ticker
- GET /api/v1/tickers/{exchange}: Query all configured tickers for an exchange

Requirements: 2.1, 2.2, 2.3, 2.4
"""

import time

from fastapi import APIRouter

from src.api.schemas import TickerMeta, TickerResponse, TickerSingleResponse
from src.dependencies import (
    TickerRepo,
    ValidExchange,
)
from src.exceptions import ClientError, ErrorCode

router = APIRouter(prefix="/api/v1", tags=["Ticker"])


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


def _calculate_age_ms(ticker_timestamp: int) -> int:
    """Calculate age of ticker data in milliseconds.
    
    Args:
        ticker_timestamp: Ticker timestamp in milliseconds
        
    Returns:
        Age in milliseconds (0 if freshly fetched)
    """
    current_time_ms = int(time.time() * 1000)
    age = current_time_ms - ticker_timestamp
    return max(0, age)


@router.get("/ticker/{exchange}/{symbol:path}", response_model=TickerSingleResponse)
async def get_ticker(
    exchange: ValidExchange,
    symbol: str,
    ticker_repo: TickerRepo,
) -> TickerSingleResponse:
    """Query real-time ticker data for a specific exchange and symbol.
    
    Returns current market snapshot including:
    - Last traded price
    - Bid/ask prices
    - 24h high/low/volume
    - 24h price change percentage
    
    Uses cache-first strategy:
    - If cached, returns immediately with age_ms indicating data freshness
    - If not cached, fetches from exchange and caches for future requests
    
    Args:
        exchange: Exchange ID (e.g., binance, okx)
        symbol: Trading pair (e.g., BTC/USDT)
        ticker_repo: Ticker repository (injected)
        
    Returns:
        TickerSingleResponse with ticker data and metadata
        
    Raises:
        ClientError: Invalid exchange or symbol
        ServerError: Exchange API error
        RateLimitError: Exchange rate limit exceeded
        
    Example:
        GET /api/v1/ticker/binance/BTC%2FUSDT
        
        Response:
        {
            "data": {
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
            },
            "meta": {
                "cached": true,
                "age_ms": 1500
            }
        }
    """
    # Validate symbol format
    _validate_symbol(symbol)
    
    # Query ticker data (cache-first, then exchange)
    ticker, cached = await ticker_repo.find(exchange, symbol)
    
    # Calculate age for cached data
    age_ms = _calculate_age_ms(ticker.timestamp) if cached else 0
    
    return TickerSingleResponse(
        data=TickerResponse(**ticker.to_dict()),
        meta=TickerMeta(cached=cached, age_ms=age_ms),
    )


@router.get("/tickers/{exchange}")
async def get_all_tickers(
    exchange: ValidExchange,
    ticker_repo: TickerRepo,
) -> dict:
    """Query all configured tickers for an exchange.
    
    Returns ticker data for all symbols configured for the specified exchange.
    Partial failures are returned in the errors array.
    
    Args:
        exchange: Exchange ID (e.g., binance, okx)
        ticker_repo: Ticker repository (injected)
        
    Returns:
        Dict with data (symbol -> ticker) and errors array
        
    Raises:
        ClientError: Invalid exchange
        
    Example:
        GET /api/v1/tickers/binance
        
        Response:
        {
            "data": {
                "BTC/USDT": {...},
                "ETH/USDT": {...}
            },
            "errors": [
                {"symbol": "INVALID/PAIR", "error": "Symbol not found"}
            ]
        }
    """
    from src.config import get_settings
    
    # Get configured symbols for this exchange from settings
    settings = get_settings()
    symbols: list[str] = []
    
    for ex_config in settings.exchanges:
        if ex_config.id == exchange:
            symbols = ex_config.symbols
            break
    
    if not symbols:
        return {"data": {}, "errors": []}
    
    # Fetch all tickers
    results, errors = await ticker_repo.find_all(exchange, symbols)
    
    # Convert to response format
    data = {
        symbol: TickerResponse(**ticker.to_dict()).model_dump()
        for symbol, ticker in results.items()
    }
    
    return {"data": data, "errors": errors}
