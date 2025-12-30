"""Authentication module for Crypto Market Data Service.

Provides API token-based authentication using Bearer tokens.

Features:
- Bearer token authentication
- Token validation from environment variable
- Secure token comparison
- Dependency injection for protected routes

Requirements: Security
"""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import get_settings

# HTTP Bearer token scheme
security = HTTPBearer(
    scheme_name="Bearer Token",
    description="API authentication token",
    auto_error=True,
)


def verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]
) -> str:
    """验证 API Token.
    
    从 Authorization header 中提取 Bearer token 并验证。
    使用 secrets.compare_digest 进行安全的字符串比较，防止时序攻击。
    
    Args:
        credentials: HTTP Bearer 凭证（通过依赖注入）
        
    Returns:
        验证通过的 token
        
    Raises:
        HTTPException: Token 无效或未配置
        
    Example:
        ```python
        @router.get("/protected")
        async def protected_route(token: Annotated[str, Depends(verify_token)]):
            return {"message": "Access granted"}
        ```
        
        Request:
        ```
        GET /protected
        Authorization: Bearer your-secret-token-here
        ```
    """
    settings = get_settings()
    
    # 检查是否配置了 API Token
    if not settings.api_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API token not configured on server",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 使用安全的字符串比较（防止时序攻击）
    token = credentials.credentials
    if not secrets.compare_digest(token, settings.api_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return token


# Type alias for dependency injection
AuthToken = Annotated[str, Depends(verify_token)]
