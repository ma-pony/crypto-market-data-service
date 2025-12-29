"""API Request and Response Schemas for Crypto Market Data Service.

Defines Pydantic models for API requests and responses:
- OHLCV data schemas
- Ticker data schemas
- Batch request/response schemas
- Pagination and metadata schemas

Requirements: 1.5, 2.4, 3.2
"""

from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ==================== OHLCV Schemas ====================


class OHLCVResponse(BaseModel):
    """OHLCV data response model.
    
    Represents a single K-line (candlestick) data point.
    All price and volume fields are strings to preserve precision.
    """
    
    exchange: str = Field(..., description="Exchange ID (e.g., binance, okx)")
    symbol: str = Field(..., description="Trading pair (e.g., BTC/USDT)")
    timeframe: str = Field(..., description="K-line timeframe (e.g., 1m, 1h, 1d)")
    timestamp: int = Field(..., description="K-line timestamp in milliseconds")
    open: str = Field(..., description="Opening price (8 decimal places)")
    high: str = Field(..., description="Highest price (8 decimal places)")
    low: str = Field(..., description="Lowest price (8 decimal places)")
    close: str = Field(..., description="Closing price (8 decimal places)")
    volume: str = Field(..., description="Trading volume (4 decimal places)")


class PaginationInfo(BaseModel):
    """Pagination information for list responses.
    
    Provides cursor-based pagination support.
    """
    
    next_cursor: Optional[str] = Field(
        None,
        description="Cursor for next page (timestamp of last record). None if no more data.",
    )


class OHLCVListMeta(BaseModel):
    """Metadata for OHLCV list responses.
    
    Provides information about query execution and caching.
    """
    
    cached: bool = Field(..., description="Whether data was served from cache")
    query_ms: int = Field(..., description="Query execution time in milliseconds")


class OHLCVListResponse(BaseModel):
    """OHLCV list response with pagination and metadata.
    
    Standard response format for OHLCV queries.
    """
    
    data: List[OHLCVResponse] = Field(..., description="List of OHLCV records")
    pagination: PaginationInfo = Field(..., description="Pagination information")
    meta: OHLCVListMeta = Field(..., description="Query metadata")


# ==================== Ticker Schemas ====================


class TickerResponse(BaseModel):
    """Ticker data response model.
    
    Represents real-time market snapshot for a trading pair.
    All price and volume fields are strings to preserve precision.
    """
    
    exchange: str = Field(..., description="Exchange ID (e.g., binance, okx)")
    symbol: str = Field(..., description="Trading pair (e.g., BTC/USDT)")
    last: str = Field(..., description="Last traded price")
    bid: Optional[str] = Field(None, description="Best bid price")
    ask: Optional[str] = Field(None, description="Best ask price")
    high_24h: Optional[str] = Field(None, description="24-hour high price")
    low_24h: Optional[str] = Field(None, description="24-hour low price")
    volume_24h: Optional[str] = Field(None, description="24-hour trading volume")
    change_pct_24h: Optional[str] = Field(None, description="24-hour price change percentage")
    timestamp: int = Field(..., description="Ticker timestamp in milliseconds")


class TickerMeta(BaseModel):
    """Metadata for ticker responses.
    
    Provides information about caching and data freshness.
    """
    
    cached: bool = Field(..., description="Whether data was served from cache")
    age_ms: int = Field(
        ...,
        description="Age of cached data in milliseconds (0 if freshly fetched)",
    )


class TickerSingleResponse(BaseModel):
    """Single ticker response with metadata.
    
    Standard response format for single ticker queries.
    """
    
    data: TickerResponse = Field(..., description="Ticker data")
    meta: TickerMeta = Field(..., description="Query metadata")


# ==================== Batch Request/Response Schemas ====================


class BatchRequest(BaseModel):
    """Batch OHLCV query request.
    
    Allows querying multiple symbols in a single request.
    Maximum 20 symbols per request.
    """
    
    exchange: str = Field(..., description="Exchange ID (e.g., binance, okx)")
    symbols: List[str] = Field(
        ...,
        max_length=20,
        description="List of trading pairs (max 20)",
    )
    timeframe: str = Field(..., description="K-line timeframe (e.g., 1m, 1h, 1d)")
    start: Optional[int] = Field(None, description="Start timestamp in milliseconds")
    end: Optional[int] = Field(None, description="End timestamp in milliseconds")


class BatchErrorItem(BaseModel):
    """Error information for a single symbol in batch request.
    
    Used when a symbol fails in a batch query.
    """
    
    symbol: str = Field(..., description="Trading pair that failed")
    error: str = Field(..., description="Error message")


class BatchResponse(BaseModel):
    """Batch OHLCV query response.
    
    Returns data for successful symbols and errors for failed ones.
    Supports partial success - some symbols may succeed while others fail.
    """
    
    data: dict[str, List[OHLCVResponse]] = Field(
        ...,
        description="OHLCV data by symbol (symbol -> list of OHLCV records)",
    )
    errors: List[BatchErrorItem] = Field(
        default_factory=list,
        description="List of errors for failed symbols",
    )
