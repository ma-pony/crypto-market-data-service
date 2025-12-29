"""Exchange client module for Crypto Market Data Service.

Provides unified access to cryptocurrency exchanges via CCXT.

Features:
- Async CCXT wrapper
- OHLCV and Ticker data fetching
- Rate limit handling
- Health check for monitoring

Requirements: 4.1, 4.4, 4.5
"""

import time
from decimal import Decimal
from typing import Optional

import ccxt.async_support as ccxt

from src.exceptions import ErrorCode, RateLimitError, ServerError
from src.models import OHLCV, Ticker


class ExchangeClient:
    """交易所客户端（CCXT 封装）.
    
    提供统一的交易所数据访问接口，支持：
    - 获取 OHLCV K线数据
    - 获取 Ticker 实时行情
    - 自动处理速率限制
    
    Attributes:
        exchange_id: 交易所 ID (binance, okx 等)
    
    Example:
        ```python
        client = ExchangeClient("binance", api_key="...", secret="...")
        await client.connect()
        ohlcv = await client.fetch_ohlcv("BTC/USDT", "1h")
        await client.disconnect()
        ```
    """
    
    # 时间周期对应的毫秒数
    TIMEFRAME_MS: dict[str, int] = {
        "1m": 60_000,
        "3m": 180_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "2h": 7_200_000,
        "4h": 14_400_000,
        "6h": 21_600_000,
        "8h": 28_800_000,
        "12h": 43_200_000,
        "1d": 86_400_000,
        "3d": 259_200_000,
        "1w": 604_800_000,
        "1M": 2_592_000_000,
    }
    
    def __init__(
        self,
        exchange_id: str,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
    ):
        """初始化交易所客户端.
        
        Args:
            exchange_id: 交易所 ID (binance, okx, bybit 等)
            api_key: API Key（可选，用于私有接口）
            secret: API Secret（可选，用于私有接口）
        """
        self.exchange_id = exchange_id
        self._api_key = api_key
        self._secret = secret
        self._client: Optional[ccxt.Exchange] = None
    
    async def connect(self) -> None:
        """建立交易所连接并加载市场信息."""
        exchange_class = getattr(ccxt, self.exchange_id)
        self._client = exchange_class({
            "apiKey": self._api_key,
            "secret": self._secret,
            "enableRateLimit": True,  # 启用内置速率限制
        })
        await self._client.load_markets()
    
    async def disconnect(self) -> None:
        """关闭交易所连接."""
        if self._client:
            await self._client.close()
            self._client = None
    
    async def health_check(self) -> bool:
        """检查交易所连接健康状态.
        
        通过获取服务器时间来验证连接。
        
        Returns:
            True 如果连接正常，否则 False
        """
        if not self._client:
            return False
        try:
            await self._client.fetch_time()
            return True
        except Exception:
            return False
    
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None,
        limit: int = 500,
    ) -> list[OHLCV]:
        """获取 OHLCV K线数据.
        
        Args:
            symbol: 交易对 (BTC/USDT)
            timeframe: K线周期 (1m, 5m, 1h, 1d 等)
            since: 起始时间戳（毫秒），可选
            limit: 返回记录数限制，默认 500
            
        Returns:
            OHLCV 记录列表
            
        Raises:
            RateLimitError: 触发交易所速率限制
            ServerError: 交易所 API 错误
        """
        if not self._client:
            raise ServerError(
                ErrorCode.EXCHANGE_ERROR,
                "Exchange client not connected",
                {"exchange": self.exchange_id},
            )
        
        try:
            data = await self._client.fetch_ohlcv(
                symbol, 
                timeframe, 
                since, 
                limit
            )
            
            return [
                OHLCV(
                    exchange=self.exchange_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=int(row[0]),
                    open=Decimal(str(row[1])),
                    high=Decimal(str(row[2])),
                    low=Decimal(str(row[3])),
                    close=Decimal(str(row[4])),
                    volume=Decimal(str(row[5])),
                )
                for row in data
            ]
        except ccxt.RateLimitExceeded:
            raise RateLimitError(self.exchange_id, retry_after=60)
        except ccxt.BaseError as e:
            raise ServerError(
                ErrorCode.EXCHANGE_ERROR,
                str(e),
                {"exchange": self.exchange_id, "symbol": symbol},
            )
    
    async def fetch_ticker(self, symbol: str) -> Ticker:
        """获取 Ticker 实时行情.
        
        Args:
            symbol: 交易对 (BTC/USDT)
            
        Returns:
            Ticker 数据
            
        Raises:
            RateLimitError: 触发交易所速率限制
            ServerError: 交易所 API 错误
        """
        if not self._client:
            raise ServerError(
                ErrorCode.EXCHANGE_ERROR,
                "Exchange client not connected",
                {"exchange": self.exchange_id},
            )
        
        try:
            data = await self._client.fetch_ticker(symbol)
            
            return Ticker(
                exchange=self.exchange_id,
                symbol=symbol,
                last=Decimal(str(data["last"])),
                bid=Decimal(str(data["bid"])) if data.get("bid") else None,
                ask=Decimal(str(data["ask"])) if data.get("ask") else None,
                high_24h=Decimal(str(data["high"])) if data.get("high") else None,
                low_24h=Decimal(str(data["low"])) if data.get("low") else None,
                volume_24h=(
                    Decimal(str(data["quoteVolume"])) 
                    if data.get("quoteVolume") else None
                ),
                change_pct_24h=(
                    Decimal(str(data["percentage"])) 
                    if data.get("percentage") else None
                ),
                timestamp=(
                    int(data["timestamp"]) 
                    if data.get("timestamp") 
                    else int(time.time() * 1000)
                ),
            )
        except ccxt.RateLimitExceeded:
            raise RateLimitError(self.exchange_id, retry_after=60)
        except ccxt.BaseError as e:
            raise ServerError(
                ErrorCode.EXCHANGE_ERROR,
                str(e),
                {"exchange": self.exchange_id, "symbol": symbol},
            )
    
    def get_timeframe_ms(self, timeframe: str) -> int:
        """获取时间周期对应的毫秒数.
        
        Args:
            timeframe: K线周期
            
        Returns:
            毫秒数
        """
        return self.TIMEFRAME_MS.get(timeframe, 60_000)
