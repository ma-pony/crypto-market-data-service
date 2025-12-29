"""Repository layer for Crypto Market Data Service.

Provides data access abstraction for OHLCV and Ticker data.

Features:
- OHLCVRepository: OHLCV data access with cache-first strategy
- TickerRepository: Ticker data access with cache + exchange fallback

Requirements: 1.1, 1.2, 2.1, 2.2, 8.1, 8.2, 8.3
"""

from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import ClientError, ErrorCode
from src.infrastructure.cache import Cache
from src.infrastructure.exchange import ExchangeClient
from src.models import OHLCV, Ticker


class OHLCVRepository:
    """K线数据仓库.
    
    提供 OHLCV 数据的存储和查询功能：
    - save(): 批量保存（upsert）
    - find(): 缓存优先查询，支持游标分页
    
    使用依赖注入的 session，不内部管理数据库会话。
    
    Attributes:
        cache: Redis 缓存实例
    
    Example:
        ```python
        repo = OHLCVRepository(cache)
        async with db.session() as session:
            await repo.save(session, records)
            results, cursor, cached = await repo.find(
                session, "binance", "BTC/USDT", "1h"
            )
        ```
    """
    
    def __init__(self, cache: Cache):
        """初始化 OHLCV Repository.
        
        Args:
            cache: Redis 缓存实例
        """
        self.cache = cache
    
    async def save(
        self, 
        session: AsyncSession, 
        records: list[OHLCV]
    ) -> int:
        """批量保存 OHLCV 数据.
        
        使用 PostgreSQL upsert (ON CONFLICT DO UPDATE) 实现幂等写入。
        同时更新 Redis 缓存。
        
        Args:
            session: 数据库会话（由调用方管理）
            records: OHLCV 记录列表
            
        Returns:
            保存的记录数
            
        Note:
            - 重复数据会更新已存在的记录
            - 缓存更新是 write-through 模式
        """
        if not records:
            return 0
        
        # 构建批量 upsert 语句
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
        ])
        
        # ON CONFLICT DO UPDATE - 更新已存在的记录
        stmt = stmt.on_conflict_do_update(
            constraint='uq_ohlcv_key',
            set_={
                'open': stmt.excluded.open,
                'high': stmt.excluded.high,
                'low': stmt.excluded.low,
                'close': stmt.excluded.close,
                'volume': stmt.excluded.volume,
            }
        )
        
        await session.execute(stmt)
        
        # 更新缓存 (write-through)
        await self.cache.cache_ohlcv(records)
        
        return len(records)
    
    async def find(
        self,
        session: AsyncSession,
        exchange: str,
        symbol: str,
        timeframe: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: int = 1000,
        cursor: Optional[str] = None,
    ) -> tuple[list[OHLCV], Optional[str], bool]:
        """查询 OHLCV 数据.
        
        采用缓存优先策略：
        1. 无游标且 limit <= 500 时，先查缓存
        2. 缓存未命中或有游标时，查数据库
        
        支持游标分页，避免大数据集的 offset 性能问题。
        
        Args:
            session: 数据库会话
            exchange: 交易所 ID
            symbol: 交易对
            timeframe: K线周期
            start: 起始时间戳（毫秒），可选
            end: 结束时间戳（毫秒），可选
            limit: 返回记录数限制，默认 1000，最大 1000
            cursor: 分页游标（上一页最后一条记录的 timestamp）
            
        Returns:
            tuple: (数据列表, 下一页游标, 是否来自缓存)
            - 数据列表: OHLCV 记录，按 timestamp 升序
            - 下一页游标: 如果有更多数据则返回游标，否则 None
            - 是否来自缓存: True 表示数据来自 Redis 缓存
        """
        # 限制最大返回数
        limit = min(limit, 1000)
        
        # 尝试缓存（仅当无游标且 limit 较小时）
        if not cursor and limit <= 500:
            cached = await self.cache.get_ohlcv(
                exchange, symbol, timeframe, start, end, limit
            )
            if cached:
                return cached, None, True
        
        # 构建查询条件
        conditions = [
            OHLCV.exchange == exchange,
            OHLCV.symbol == symbol,
            OHLCV.timeframe == timeframe,
        ]
        
        if start is not None:
            conditions.append(OHLCV.timestamp >= start)
        if end is not None:
            conditions.append(OHLCV.timestamp <= end)
        if cursor is not None:
            # 游标分页：获取 timestamp > cursor 的记录
            conditions.append(OHLCV.timestamp > int(cursor))
        
        # 执行查询（多取一条用于判断是否有下一页）
        stmt = (
            select(OHLCV)
            .where(and_(*conditions))
            .order_by(OHLCV.timestamp.asc())
            .limit(limit + 1)
        )
        
        result = await session.execute(stmt)
        rows = result.scalars().all()
        
        # 判断是否有更多数据
        has_more = len(rows) > limit
        records = list(rows[:limit])
        
        # 生成下一页游标
        next_cursor = None
        if has_more and records:
            next_cursor = str(records[-1].timestamp)
        
        return records, next_cursor, False



class TickerRepository:
    """Ticker 数据仓库.
    
    提供 Ticker 数据的存储和查询功能：
    - save(): 保存到缓存
    - find(): 缓存优先，未命中时从交易所获取
    
    Ticker 数据不持久化到数据库，仅缓存在 Redis 中。
    
    Attributes:
        cache: Redis 缓存实例
        clients: 交易所客户端字典 {exchange_id: ExchangeClient}
    
    Example:
        ```python
        repo = TickerRepository(cache, clients)
        ticker, cached = await repo.find("binance", "BTC/USDT")
        ```
    """
    
    def __init__(
        self, 
        cache: Cache, 
        clients: dict[str, ExchangeClient]
    ):
        """初始化 Ticker Repository.
        
        Args:
            cache: Redis 缓存实例
            clients: 交易所客户端字典
        """
        self.cache = cache
        self.clients = clients
    
    async def save(self, ticker: Ticker) -> None:
        """保存 Ticker 数据到缓存.
        
        Args:
            ticker: Ticker 数据
        """
        await self.cache.cache_ticker(ticker)
    
    async def find(
        self, 
        exchange: str, 
        symbol: str
    ) -> tuple[Optional[Ticker], bool]:
        """查询 Ticker 数据.
        
        采用缓存优先策略：
        1. 先查 Redis 缓存
        2. 缓存未命中时，从交易所获取并缓存
        
        Args:
            exchange: 交易所 ID
            symbol: 交易对
            
        Returns:
            tuple: (Ticker 数据, 是否来自缓存)
            - Ticker 数据: 如果找到则返回 Ticker，否则 None
            - 是否来自缓存: True 表示数据来自 Redis 缓存
            
        Raises:
            ClientError: 未知的交易所
            ServerError: 交易所 API 错误
            RateLimitError: 触发交易所速率限制
        """
        # 先查缓存
        cached = await self.cache.get_ticker(exchange, symbol)
        if cached:
            return cached, True
        
        # 验证交易所
        client = self.clients.get(exchange)
        if not client:
            raise ClientError(
                ErrorCode.INVALID_EXCHANGE,
                f"Unknown exchange: {exchange}",
                {"exchange": exchange},
            )
        
        # 从交易所获取
        ticker = await client.fetch_ticker(symbol)
        
        # 保存到缓存
        await self.save(ticker)
        
        return ticker, False
    
    async def find_all(
        self, 
        exchange: str, 
        symbols: list[str]
    ) -> tuple[dict[str, Ticker], list[dict[str, str]]]:
        """批量查询 Ticker 数据.
        
        Args:
            exchange: 交易所 ID
            symbols: 交易对列表
            
        Returns:
            tuple: (成功的 Ticker 字典, 错误列表)
            - Ticker 字典: {symbol: Ticker}
            - 错误列表: [{"symbol": str, "error": str}]
        """
        results: dict[str, Ticker] = {}
        errors: list[dict[str, str]] = []
        
        for symbol in symbols:
            try:
                ticker, _ = await self.find(exchange, symbol)
                if ticker:
                    results[symbol] = ticker
            except Exception as e:
                errors.append({
                    "symbol": symbol,
                    "error": str(e),
                })
        
        return results, errors
