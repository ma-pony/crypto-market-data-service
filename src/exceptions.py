"""Exception definitions for Crypto Market Data Service.

Provides structured error handling with:
- Error codes for programmatic handling
- Human-readable messages
- Additional details for debugging
"""

from enum import Enum
from typing import Any, Optional


class ErrorCode(str, Enum):
    """错误代码枚举"""
    
    # 客户端错误 (4xx)
    INVALID_SYMBOL = "INVALID_SYMBOL"
    INVALID_TIMEFRAME = "INVALID_TIMEFRAME"
    INVALID_TIME_RANGE = "INVALID_TIME_RANGE"
    INVALID_EXCHANGE = "INVALID_EXCHANGE"
    BATCH_SIZE_EXCEEDED = "BATCH_SIZE_EXCEEDED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    
    # 服务端错误 (5xx)
    EXCHANGE_ERROR = "EXCHANGE_ERROR"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    CACHE_ERROR = "CACHE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class MarketDataError(Exception):
    """市场数据服务基础异常类"""
    
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: Optional[dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)
    
    def to_dict(self) -> dict[str, Any]:
        """转换为API响应格式"""
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details,
            }
        }
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code.value}, message={self.message!r})"


class ClientError(MarketDataError):
    """客户端错误 (4xx)
    
    用于表示由客户端请求引起的错误，如：
    - 无效的参数
    - 不存在的资源
    - 超出限制的请求
    """
    pass


class ServerError(MarketDataError):
    """服务端错误 (5xx)
    
    用于表示服务端内部错误，如：
    - 数据库连接失败
    - 缓存服务不可用
    - 交易所API错误
    """
    pass


class RateLimitError(ServerError):
    """速率限制错误
    
    当交易所API返回速率限制错误时抛出。
    包含建议的重试等待时间。
    """
    
    def __init__(self, exchange: str, retry_after: int = 60):
        super().__init__(
            code=ErrorCode.RATE_LIMIT_ERROR,
            message=f"Rate limit exceeded for {exchange}",
            details={
                "exchange": exchange,
                "retry_after_seconds": retry_after,
            },
        )
        self.exchange = exchange
        self.retry_after = retry_after
