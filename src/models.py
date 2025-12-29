"""Domain models for Crypto Market Data Service.

Implements:
- OHLCV: K-line data model (SQLAlchemy ORM + serialization)
- Ticker: Real-time ticker data model (dataclass + serialization)

Requirements: 1.6, 2.4, 8.1
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class."""
    pass


class OHLCV(Base):
    """K线数据模型 (OHLCV - Open, High, Low, Close, Volume).
    
    存储交易所的K线历史数据，支持多交易所、多交易对、多时间周期。
    
    Attributes:
        id: 唯一标识符 (UUID)
        exchange: 交易所ID (binance, okx等)
        symbol: 交易对 (BTC/USDT, ETH/USDT等)
        timeframe: K线周期 (1m, 5m, 1h, 1d等)
        timestamp: K线时间戳 (毫秒)
        open: 开盘价 (8位小数精度)
        high: 最高价 (8位小数精度)
        low: 最低价 (8位小数精度)
        close: 收盘价 (8位小数精度)
        volume: 成交量 (4位小数精度)
        created_at: 记录创建时间
    """
    
    __tablename__ = "ohlcv"
    
    id: Mapped[str] = mapped_column(
        String(36), 
        primary_key=True, 
        default=lambda: str(uuid.uuid4())
    )
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        server_default=func.now()
    )
    
    __table_args__ = (
        UniqueConstraint(
            'exchange', 'symbol', 'timeframe', 'timestamp', 
            name='uq_ohlcv_key'
        ),
        Index(
            'idx_ohlcv_lookup', 
            'exchange', 'symbol', 'timeframe', 'timestamp'
        ),
    )
    
    def to_dict(self) -> dict[str, Any]:
        """序列化为字典格式.
        
        价格保留8位小数，成交量保留4位小数。
        
        Returns:
            包含所有字段的字典
        """
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OHLCV":
        """从字典创建实例.
        
        Args:
            data: 包含OHLCV字段的字典
            
        Returns:
            OHLCV实例
        """
        return cls(
            exchange=data["exchange"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            timestamp=data["timestamp"],
            open=Decimal(data["open"]),
            high=Decimal(data["high"]),
            low=Decimal(data["low"]),
            close=Decimal(data["close"]),
            volume=Decimal(data["volume"]),
        )
    
    def __eq__(self, other: object) -> bool:
        """比较两个OHLCV对象是否相等（用于属性测试）."""
        if not isinstance(other, OHLCV):
            return NotImplemented
        return (
            self.exchange == other.exchange
            and self.symbol == other.symbol
            and self.timeframe == other.timeframe
            and self.timestamp == other.timestamp
            and self.open == other.open
            and self.high == other.high
            and self.low == other.low
            and self.close == other.close
            and self.volume == other.volume
        )
    
    def __repr__(self) -> str:
        return (
            f"OHLCV(exchange={self.exchange!r}, symbol={self.symbol!r}, "
            f"timeframe={self.timeframe!r}, timestamp={self.timestamp}, "
            f"close={self.close})"
        )


@dataclass
class Ticker:
    """Ticker数据模型（实时行情快照，不持久化到数据库）.
    
    存储交易所的实时行情数据，包括当前价格和24小时统计。
    
    Attributes:
        exchange: 交易所ID
        symbol: 交易对
        last: 最新成交价
        bid: 买一价 (可选)
        ask: 卖一价 (可选)
        high_24h: 24小时最高价 (可选)
        low_24h: 24小时最低价 (可选)
        volume_24h: 24小时成交量 (可选)
        change_pct_24h: 24小时涨跌幅百分比 (可选)
        timestamp: 数据时间戳 (毫秒)
    """
    
    exchange: str
    symbol: str
    last: Decimal
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    high_24h: Optional[Decimal] = None
    low_24h: Optional[Decimal] = None
    volume_24h: Optional[Decimal] = None
    change_pct_24h: Optional[Decimal] = None
    timestamp: int = field(default=0)
    
    def to_dict(self) -> dict[str, Any]:
        """序列化为字典格式.
        
        可选字段为None时保持None，非None时转为字符串。
        
        Returns:
            包含所有字段的字典
        """
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "last": str(self.last),
            "bid": str(self.bid) if self.bid is not None else None,
            "ask": str(self.ask) if self.ask is not None else None,
            "high_24h": str(self.high_24h) if self.high_24h is not None else None,
            "low_24h": str(self.low_24h) if self.low_24h is not None else None,
            "volume_24h": str(self.volume_24h) if self.volume_24h is not None else None,
            "change_pct_24h": str(self.change_pct_24h) if self.change_pct_24h is not None else None,
            "timestamp": self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Ticker":
        """从字典创建实例.
        
        Args:
            data: 包含Ticker字段的字典
            
        Returns:
            Ticker实例
        """
        return cls(
            exchange=data["exchange"],
            symbol=data["symbol"],
            last=Decimal(data["last"]),
            bid=Decimal(data["bid"]) if data.get("bid") is not None else None,
            ask=Decimal(data["ask"]) if data.get("ask") is not None else None,
            high_24h=Decimal(data["high_24h"]) if data.get("high_24h") is not None else None,
            low_24h=Decimal(data["low_24h"]) if data.get("low_24h") is not None else None,
            volume_24h=Decimal(data["volume_24h"]) if data.get("volume_24h") is not None else None,
            change_pct_24h=Decimal(data["change_pct_24h"]) if data.get("change_pct_24h") is not None else None,
            timestamp=data["timestamp"],
        )
    
    def __repr__(self) -> str:
        return (
            f"Ticker(exchange={self.exchange!r}, symbol={self.symbol!r}, "
            f"last={self.last}, timestamp={self.timestamp})"
        )
