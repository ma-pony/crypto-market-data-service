"""Database connection module for Crypto Market Data Service.

Provides async database connectivity using SQLAlchemy 2.0 with asyncpg.

Features:
- Async engine with connection pooling
- Session factory with automatic commit/rollback
- Health check for monitoring

Requirements: 8.1, 7.1
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """异步数据库连接管理器.
    
    使用 SQLAlchemy 2.0 异步引擎和会话工厂。
    
    Attributes:
        engine: SQLAlchemy 异步引擎
        session_factory: 异步会话工厂
    
    Example:
        ```python
        db = Database("postgresql://user:pass@localhost/db")
        async with db.session() as session:
            result = await session.execute(select(Model))
        ```
    """
    
    def __init__(self, url: str, pool_size: int = 10):
        """初始化数据库连接.
        
        Args:
            url: PostgreSQL 连接字符串 (postgresql:// 或 postgresql+asyncpg://)
            pool_size: 连接池大小，默认10
        """
        # 确保使用 asyncpg 驱动
        async_url = url
        if url.startswith("postgresql://"):
            async_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        
        self.engine: AsyncEngine = create_async_engine(
            async_url,
            pool_size=pool_size,
            pool_pre_ping=True,  # 连接健康检查
            echo=False,
        )
        
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取数据库会话（带自动提交/回滚）.
        
        使用上下文管理器确保会话正确关闭。
        正常退出时自动提交，异常时自动回滚。
        
        Yields:
            AsyncSession: 数据库会话
            
        Example:
            ```python
            async with db.session() as session:
                session.add(model)
                # 自动提交
            ```
        """
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    
    async def health_check(self) -> bool:
        """检查数据库连接健康状态.
        
        执行简单的连接测试来验证数据库可用性。
        
        Returns:
            True 如果数据库连接正常，否则 False
        """
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
    
    async def dispose(self) -> None:
        """关闭数据库连接池.
        
        应在应用关闭时调用以释放所有连接。
        """
        await self.engine.dispose()
