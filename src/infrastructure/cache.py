"""Redis cache module for Crypto Market Data Service.

Provides caching for OHLCV and Ticker data using Redis.

Features:
- OHLCV: Redis Sorted Set (score = timestamp) with size limit
- Ticker: Redis String with TTL
- Health check for monitoring

Requirements: 8.3, 8.4, 8.5
"""

import json
from typing import TYPE_CHECKING, Optional

import redis.asyncio as redis

if TYPE_CHECKING:
    from src.models import OHLCV, Ticker


class Cache:
    """Redis 缓存管理器.
    
    使用 Redis 存储 OHLCV 和 Ticker 数据：
    - OHLCV: Sorted Set，按 timestamp 排序，限制大小
    - Ticker: String + TTL，自动过期
    
    Attributes:
        url: Redis 连接 URL
        ohlcv_cache_size: OHLCV 缓存大小限制
        ticker_ttl: Ticker 缓存 TTL（秒）
    
    Example:
        ```python
        cache = Cache("redis://localhost:6379")
        await cache.connect()
        await cache.cache_ohlcv(records)
        await cache.disconnect()
        ```
    """
    
    def __init__(
        self, 
        url: str, 
        ohlcv_cache_size: int = 500, 
        ticker_ttl: int = 10
    ):
        """初始化缓存配置.
        
        Args:
            url: Redis 连接 URL (redis://host:port)
            ohlcv_cache_size: 每个 (exchange, symbol, timeframe) 组合的最大缓存条数
            ticker_ttl: Ticker 数据的 TTL（秒）
        """
        self.url = url
        self.ohlcv_cache_size = ohlcv_cache_size
        self.ticker_ttl = ticker_ttl
        self._client: Optional[redis.Redis] = None
    
    async def connect(self) -> None:
        """建立 Redis 连接."""
        self._client = redis.from_url(self.url, decode_responses=True)
    
    async def disconnect(self) -> None:
        """关闭 Redis 连接."""
        if self._client:
            await self._client.close()
            self._client = None
    
    async def health_check(self) -> bool:
        """检查 Redis 连接健康状态.
        
        Returns:
            True 如果 Redis 连接正常，否则 False
        """
        if not self._client:
            return False
        try:
            await self._client.ping()
            return True
        except Exception:
            return False
    
    # ==================== OHLCV 缓存 ====================
    
    def _ohlcv_key(self, exchange: str, symbol: str, timeframe: str) -> str:
        """生成 OHLCV 缓存键.
        
        Args:
            exchange: 交易所 ID
            symbol: 交易对
            timeframe: K线周期
            
        Returns:
            Redis 键名
        """
        return f"ohlcv:{exchange}:{symbol}:{timeframe}"
    
    async def cache_ohlcv(self, records: list["OHLCV"]) -> None:
        """缓存 OHLCV 数据.
        
        使用 Redis Sorted Set 存储，timestamp 作为 score。
        自动裁剪超出大小限制的旧数据。
        
        Args:
            records: OHLCV 记录列表
        """
        if not records or not self._client:
            return
        
        # 按 (exchange, symbol, timeframe) 分组
        by_key: dict[str, list["OHLCV"]] = {}
        for r in records:
            key = self._ohlcv_key(r.exchange, r.symbol, r.timeframe)
            by_key.setdefault(key, []).append(r)
        
        # 使用 pipeline 批量操作
        pipe = self._client.pipeline()
        for key, recs in by_key.items():
            # 添加数据到 Sorted Set
            for r in recs:
                pipe.zadd(key, {json.dumps(r.to_dict()): r.timestamp})
            # 裁剪旧数据，保留最新的 ohlcv_cache_size 条
            pipe.zremrangebyrank(key, 0, -(self.ohlcv_cache_size + 1))
        
        await pipe.execute()
    
    async def get_ohlcv(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: int = 500,
    ) -> list["OHLCV"]:
        """从缓存获取 OHLCV 数据.
        
        Args:
            exchange: 交易所 ID
            symbol: 交易对
            timeframe: K线周期
            start: 起始时间戳（毫秒），可选
            end: 结束时间戳（毫秒），可选
            limit: 返回记录数限制
            
        Returns:
            OHLCV 记录列表，按 timestamp 升序排列
        """
        if not self._client:
            return []
        
        # 延迟导入避免循环依赖
        from src.models import OHLCV
        
        key = self._ohlcv_key(exchange, symbol, timeframe)
        
        # 使用 ZRANGEBYSCORE 按时间范围查询
        min_score = start if start is not None else "-inf"
        max_score = end if end is not None else "+inf"
        
        data = await self._client.zrangebyscore(
            key, 
            min_score, 
            max_score, 
            start=0, 
            num=limit
        )
        
        return [OHLCV.from_dict(json.loads(item)) for item in data]
    
    # ==================== Ticker 缓存 ====================
    
    def _ticker_key(self, exchange: str, symbol: str) -> str:
        """生成 Ticker 缓存键.
        
        Args:
            exchange: 交易所 ID
            symbol: 交易对
            
        Returns:
            Redis 键名
        """
        return f"ticker:{exchange}:{symbol}"
    
    async def cache_ticker(self, ticker: "Ticker") -> None:
        """缓存 Ticker 数据.
        
        使用 Redis String + TTL 存储，自动过期。
        
        Args:
            ticker: Ticker 数据
        """
        if not self._client:
            return
        
        key = self._ticker_key(ticker.exchange, ticker.symbol)
        await self._client.setex(
            key, 
            self.ticker_ttl, 
            json.dumps(ticker.to_dict())
        )
    
    async def get_ticker(
        self, 
        exchange: str, 
        symbol: str
    ) -> Optional["Ticker"]:
        """从缓存获取 Ticker 数据.
        
        Args:
            exchange: 交易所 ID
            symbol: 交易对
            
        Returns:
            Ticker 数据，如果缓存未命中则返回 None
        """
        if not self._client:
            return None
        
        # 延迟导入避免循环依赖
        from src.models import Ticker
        
        key = self._ticker_key(exchange, symbol)
        data = await self._client.get(key)
        
        if data:
            return Ticker.from_dict(json.loads(data))
        return None
    
    async def get_ticker_age(
        self, 
        exchange: str, 
        symbol: str
    ) -> Optional[int]:
        """获取 Ticker 缓存的年龄（毫秒）.
        
        Args:
            exchange: 交易所 ID
            symbol: 交易对
            
        Returns:
            缓存年龄（毫秒），如果缓存不存在则返回 None
        """
        if not self._client:
            return None
        
        key = self._ticker_key(exchange, symbol)
        ttl = await self._client.ttl(key)
        
        if ttl > 0:
            # 计算已过去的时间
            age_seconds = self.ticker_ttl - ttl
            return age_seconds * 1000
        return None
