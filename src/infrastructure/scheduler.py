"""Data collection scheduler for Crypto Market Data Service.

Provides automated data collection using APScheduler:
- OHLCV collection at timeframe intervals
- Ticker collection every 10 seconds
- Gap filling for historical data
- Rate limit pause mechanism
- Exponential backoff retry

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
"""

import asyncio
import time
from typing import TYPE_CHECKING

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.exceptions import RateLimitError

if TYPE_CHECKING:
    from src.config import ExchangeConfig
    from src.infrastructure.database import Database
    from src.infrastructure.exchange import ExchangeClient
    from src.repositories import OHLCVRepository, TickerRepository


logger = structlog.get_logger()


class CollectionScheduler:
    """数据采集调度器.
    
    使用 APScheduler 实现定时数据采集：
    - OHLCV: 按 timeframe 间隔采集（1m 数据每分钟采集）
    - Ticker: 每 10 秒采集一次
    - 支持 rate limit 暂停机制
    
    调度器内部管理数据库会话（后台任务不通过 FastAPI 依赖注入）。
    
    Attributes:
        db: 数据库连接实例
        clients: 交易所客户端字典 {exchange_id: ExchangeClient}
        ohlcv_repo: OHLCV Repository
        ticker_repo: Ticker Repository
    
    Example:
        ```python
        scheduler = CollectionScheduler(db, clients, ohlcv_repo, ticker_repo)
        scheduler.start(exchanges, timeframes)
        # ... 应用运行中 ...
        scheduler.stop()
        ```
    """
    
    # 时间周期对应的秒数
    TIMEFRAME_SECONDS: dict[str, int] = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
        "4h": 14400,
        "6h": 21600,
        "8h": 28800,
        "12h": 43200,
        "1d": 86400,
        "3d": 259200,
        "1w": 604800,
        "1M": 2592000,
    }
    
    # Ticker 采集间隔（秒）
    TICKER_INTERVAL_SECONDS: int = 10
    
    def __init__(
        self,
        db: "Database",
        clients: dict[str, "ExchangeClient"],
        ohlcv_repo: "OHLCVRepository",
        ticker_repo: "TickerRepository",
    ):
        """初始化调度器.
        
        Args:
            db: 数据库连接实例
            clients: 交易所客户端字典
            ohlcv_repo: OHLCV Repository
            ticker_repo: Ticker Repository
        """
        self.db = db
        self.clients = clients
        self.ohlcv_repo = ohlcv_repo
        self.ticker_repo = ticker_repo
        
        # APScheduler 实例
        self._scheduler = AsyncIOScheduler()
        
        # 交易所暂停状态 {exchange_id: resume_timestamp}
        self._paused: dict[str, float] = {}
    
    def _is_paused(self, exchange: str) -> bool:
        """检查交易所是否处于暂停状态.
        
        Args:
            exchange: 交易所 ID
            
        Returns:
            True 如果交易所处于暂停状态
        """
        if exchange in self._paused:
            if time.time() < self._paused[exchange]:
                return True
            # 暂停时间已过，移除暂停状态
            del self._paused[exchange]
        return False
    
    def _pause_exchange(self, exchange: str, duration: int) -> None:
        """暂停交易所数据采集.
        
        Args:
            exchange: 交易所 ID
            duration: 暂停时长（秒）
        """
        self._paused[exchange] = time.time() + duration
        logger.warning(
            "exchange_paused",
            exchange=exchange,
            duration_seconds=duration,
            resume_at=self._paused[exchange],
        )
    
    async def _collect_ohlcv(
        self, 
        exchange: str, 
        symbol: str, 
        timeframe: str
    ) -> None:
        """采集 OHLCV 数据.
        
        内部管理数据库会话，不依赖 FastAPI 依赖注入。
        
        Args:
            exchange: 交易所 ID
            symbol: 交易对
            timeframe: K线周期
        """
        # 检查是否暂停
        if self._is_paused(exchange):
            logger.debug(
                "ohlcv_collection_skipped",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                reason="exchange_paused",
            )
            return
        
        try:
            # 从交易所获取数据
            client = self.clients.get(exchange)
            if not client:
                logger.error(
                    "ohlcv_collection_failed",
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    error="Exchange client not found",
                )
                return
            
            records = await client.fetch_ohlcv(symbol, timeframe, limit=10)
            
            # 后台任务内部管理会话
            async with self.db.session() as session:
                count = await self.ohlcv_repo.save(session, records)
            
            logger.info(
                "ohlcv_collected",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                count=count,
            )
            
        except RateLimitError as e:
            # 触发速率限制，暂停该交易所
            self._pause_exchange(exchange, e.retry_after)
            
        except Exception as e:
            logger.error(
                "ohlcv_collection_failed",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
                error_type=type(e).__name__,
            )
    
    async def _fill_ohlcv_gap(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        gap_days: int = 7,
    ) -> None:
        """补全 OHLCV 历史数据缺口.
        
        智能检测并补全缺失的数据：
        1. 检查目标时间范围内所有应该存在的时间点
        2. 找出实际缺失的时间点
        3. 只补全缺失的部分，避免重复拉取
        
        Args:
            exchange: 交易所 ID
            symbol: 交易对
            timeframe: K线周期
            gap_days: 最多补全多少天的数据，默认 7 天
        """
        # 检查是否暂停
        if self._is_paused(exchange):
            logger.debug(
                "gap_fill_skipped",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                reason="exchange_paused",
            )
            return
        
        try:
            client = self.clients.get(exchange)
            if not client:
                logger.error(
                    "gap_fill_failed",
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    error="Exchange client not found",
                )
                return
            
            # 计算时间周期的毫秒数
            timeframe_seconds = self.TIMEFRAME_SECONDS.get(timeframe, 60)
            timeframe_ms = timeframe_seconds * 1000
            
            # 计算目标时间范围
            current_time_ms = int(time.time() * 1000)
            target_start_ms = current_time_ms - (gap_days * 24 * 60 * 60 * 1000)
            
            # 查询数据库中该时间范围内的所有记录
            async with self.db.session() as session:
                from sqlalchemy import select
                from src.models import OHLCV
                
                stmt = (
                    select(OHLCV.timestamp)
                    .where(
                        OHLCV.exchange == exchange,
                        OHLCV.symbol == symbol,
                        OHLCV.timeframe == timeframe,
                        OHLCV.timestamp >= target_start_ms,
                    )
                    .order_by(OHLCV.timestamp)
                )
                
                result = await session.execute(stmt)
                existing_timestamps = set(row[0] for row in result.all())
            
            # 生成目标时间范围内所有应该存在的时间点
            # 对齐到时间周期的边界
            aligned_start = (target_start_ms // timeframe_ms) * timeframe_ms
            expected_timestamps = set()
            current = aligned_start
            while current <= current_time_ms:
                expected_timestamps.add(current)
                current += timeframe_ms
            
            # 找出缺失的时间点
            missing_timestamps = sorted(expected_timestamps - existing_timestamps)
            
            if not missing_timestamps:
                logger.debug(
                    "gap_fill_not_needed",
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    checked_range_days=gap_days,
                )
                return
            
            # 计算缺失数据的统计信息
            missing_count = len(missing_timestamps)
            expected_count = len(expected_timestamps)
            coverage_pct = ((expected_count - missing_count) / expected_count * 100) if expected_count > 0 else 0
            
            logger.info(
                "gap_fill_detected",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                missing_count=missing_count,
                expected_count=expected_count,
                coverage_pct=f"{coverage_pct:.1f}%",
                gap_days=gap_days,
            )
            
            # 将缺失的时间点分组为连续的区间，以优化 API 调用
            gaps = []
            if missing_timestamps:
                gap_start = missing_timestamps[0]
                gap_end = missing_timestamps[0]
                
                for ts in missing_timestamps[1:]:
                    if ts == gap_end + timeframe_ms:
                        # 连续的时间点，扩展当前区间
                        gap_end = ts
                    else:
                        # 不连续，保存当前区间并开始新区间
                        gaps.append((gap_start, gap_end))
                        gap_start = ts
                        gap_end = ts
                
                # 保存最后一个区间
                gaps.append((gap_start, gap_end))
            
            logger.info(
                "gap_fill_plan",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                gap_count=len(gaps),
                total_missing=missing_count,
            )
            
            # 补全每个缺口区间
            total_filled = 0
            for gap_idx, (gap_start, gap_end) in enumerate(gaps, 1):
                # 计算这个区间需要多少条记录
                gap_size = int((gap_end - gap_start) / timeframe_ms) + 1
                
                logger.debug(
                    "gap_fill_interval",
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    interval=f"{gap_idx}/{len(gaps)}",
                    start_time=gap_start,
                    end_time=gap_end,
                    size=gap_size,
                )
                
                # 分批获取数据（每次最多 1000 条）
                batch_size = 1000
                current_start = gap_start
                
                while current_start <= gap_end:
                    # 计算这一批需要获取多少条
                    remaining = int((gap_end - current_start) / timeframe_ms) + 1
                    limit = min(batch_size, remaining)
                    
                    try:
                        # 从交易所获取数据
                        records = await client.fetch_ohlcv(
                            symbol=symbol,
                            timeframe=timeframe,
                            since=current_start,
                            limit=limit,
                        )
                        
                        if not records:
                            logger.warning(
                                "gap_fill_no_data",
                                exchange=exchange,
                                symbol=symbol,
                                timeframe=timeframe,
                                since=current_start,
                            )
                            break
                        
                        # 保存到数据库
                        async with self.db.session() as save_session:
                            count = await self.ohlcv_repo.save(save_session, records)
                            total_filled += count
                        
                        # 更新起始时间为最后一条记录之后
                        current_start = records[-1].timestamp + timeframe_ms
                        
                        # 如果返回的记录数少于请求数，说明已经到最新了
                        if len(records) < limit:
                            break
                        
                        # 避免请求过快，增加延迟以防止触发 API 限制
                        await asyncio.sleep(1.0)
                        
                    except RateLimitError as e:
                        # 触发速率限制，暂停该交易所
                        self._pause_exchange(exchange, e.retry_after)
                        logger.warning(
                            "gap_fill_rate_limited",
                            exchange=exchange,
                            symbol=symbol,
                            timeframe=timeframe,
                            retry_after=e.retry_after,
                            filled_so_far=total_filled,
                        )
                        return
                    
                    except Exception as e:
                        logger.error(
                            "gap_fill_batch_failed",
                            exchange=exchange,
                            symbol=symbol,
                            timeframe=timeframe,
                            error=str(e),
                            error_type=type(e).__name__,
                            filled_so_far=total_filled,
                        )
                        # 继续处理下一个区间
                        break
            
            if total_filled > 0:
                # 计算补全后的覆盖率
                final_coverage_pct = ((expected_count - missing_count + total_filled) / expected_count * 100) if expected_count > 0 else 0
                
                logger.info(
                    "gap_filled",
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    records_filled=total_filled,
                    coverage_before=f"{coverage_pct:.1f}%",
                    coverage_after=f"{final_coverage_pct:.1f}%",
                )
            else:
                logger.warning(
                    "gap_fill_no_records",
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                )
                
        except RateLimitError as e:
            # 触发速率限制，暂停该交易所
            self._pause_exchange(exchange, e.retry_after)
            logger.warning(
                "gap_fill_rate_limited",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                retry_after=e.retry_after,
            )
            
        except Exception as e:
            logger.error(
                "gap_fill_failed",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
                error_type=type(e).__name__,
            )
    
    async def _collect_ticker(self, exchange: str, symbol: str) -> None:
        """采集 Ticker 数据.
        
        Ticker 数据不需要数据库，直接保存到缓存。
        
        Args:
            exchange: 交易所 ID
            symbol: 交易对
        """
        # 检查是否暂停
        if self._is_paused(exchange):
            logger.debug(
                "ticker_collection_skipped",
                exchange=exchange,
                symbol=symbol,
                reason="exchange_paused",
            )
            return
        
        try:
            # 从交易所获取数据
            client = self.clients.get(exchange)
            if not client:
                logger.error(
                    "ticker_collection_failed",
                    exchange=exchange,
                    symbol=symbol,
                    error="Exchange client not found",
                )
                return
            
            ticker = await client.fetch_ticker(symbol)
            
            # 保存到缓存
            await self.ticker_repo.save(ticker)
            
            logger.debug(
                "ticker_collected",
                exchange=exchange,
                symbol=symbol,
                last=str(ticker.last),
            )
            
        except RateLimitError as e:
            # 触发速率限制，暂停该交易所
            self._pause_exchange(exchange, e.retry_after)
            
        except Exception as e:
            logger.error(
                "ticker_collection_failed",
                exchange=exchange,
                symbol=symbol,
                error=str(e),
                error_type=type(e).__name__,
            )

    
    def start(
        self, 
        exchanges: list["ExchangeConfig"], 
        timeframes: list[str],
        gap_fill_enabled: bool = True,
        gap_fill_days: int = 7,
    ) -> None:
        """启动数据采集调度器.
        
        为每个 (exchange, symbol, timeframe) 组合创建 OHLCV 采集任务，
        为每个 (exchange, symbol) 组合创建 Ticker 采集任务。
        
        如果启用 gap_fill，会在启动时异步执行一次历史数据补全。
        
        Args:
            exchanges: 交易所配置列表
            timeframes: 支持的 K线周期列表
            gap_fill_enabled: 是否启用数据补全，默认 True
            gap_fill_days: 补全多少天的历史数据，默认 7 天
        """
        job_count = 0
        
        for ex in exchanges:
            for symbol in ex.symbols:
                # 为每个 timeframe 创建 OHLCV 采集任务
                for tf in timeframes:
                    interval = self.TIMEFRAME_SECONDS.get(tf, 60)
                    job_id = f"ohlcv:{ex.id}:{symbol}:{tf}"
                    
                    self._scheduler.add_job(
                        self._collect_ohlcv,
                        trigger=IntervalTrigger(seconds=interval),
                        args=[ex.id, symbol, tf],
                        id=job_id,
                        name=f"Collect OHLCV {ex.id}/{symbol}/{tf}",
                        replace_existing=True,
                    )
                    job_count += 1
                    
                    # 如果启用 gap fill，添加启动时的补全任务
                    if gap_fill_enabled:
                        # 使用 asyncio.create_task 异步执行，不阻塞启动
                        asyncio.create_task(
                            self._fill_ohlcv_gap(ex.id, symbol, tf, gap_fill_days)
                        )
                
                # 为每个 symbol 创建 Ticker 采集任务
                ticker_job_id = f"ticker:{ex.id}:{symbol}"
                
                self._scheduler.add_job(
                    self._collect_ticker,
                    trigger=IntervalTrigger(seconds=self.TICKER_INTERVAL_SECONDS),
                    args=[ex.id, symbol],
                    id=ticker_job_id,
                    name=f"Collect Ticker {ex.id}/{symbol}",
                    replace_existing=True,
                )
                job_count += 1
        
        # 启动调度器
        self._scheduler.start()
        
        logger.info(
            "scheduler_started",
            job_count=job_count,
            exchanges=[ex.id for ex in exchanges],
            timeframes=timeframes,
            gap_fill_enabled=gap_fill_enabled,
            gap_fill_days=gap_fill_days if gap_fill_enabled else None,
        )
    
    def stop(self) -> None:
        """停止数据采集调度器.
        
        优雅关闭调度器，等待当前任务完成。
        """
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("scheduler_stopped")
    
    def pause_exchange(self, exchange: str, duration: int = 60) -> None:
        """手动暂停交易所数据采集.
        
        Args:
            exchange: 交易所 ID
            duration: 暂停时长（秒），默认 60 秒
        """
        self._pause_exchange(exchange, duration)
    
    def resume_exchange(self, exchange: str) -> None:
        """恢复交易所数据采集.
        
        Args:
            exchange: 交易所 ID
        """
        if exchange in self._paused:
            del self._paused[exchange]
            logger.info("exchange_resumed", exchange=exchange)
    
    def get_paused_exchanges(self) -> dict[str, float]:
        """获取当前暂停的交易所列表.
        
        Returns:
            字典 {exchange_id: resume_timestamp}
        """
        # 清理已过期的暂停状态
        current_time = time.time()
        self._paused = {
            ex: ts for ex, ts in self._paused.items() 
            if ts > current_time
        }
        return self._paused.copy()
    
    def is_running(self) -> bool:
        """检查调度器是否正在运行.
        
        Returns:
            True 如果调度器正在运行
        """
        return self._scheduler.running
    
    def get_job_count(self) -> int:
        """获取当前调度任务数量.
        
        Returns:
            任务数量
        """
        return len(self._scheduler.get_jobs())
