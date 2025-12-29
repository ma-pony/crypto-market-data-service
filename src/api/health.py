"""Health check route for Crypto Market Data Service.

Provides health monitoring endpoint for service status.

Features:
- Check PostgreSQL connection status
- Check Redis connection status
- Check exchange connections status
- Return overall health status

Requirements: 7.1, 7.2
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.dependencies import CacheDep, ExchangeClients

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check(
    request: Request,
    cache: CacheDep,
    clients: ExchangeClients,
) -> JSONResponse:
    """健康检查端点.
    
    检查所有关键组件的健康状态：
    - PostgreSQL 数据库连接
    - Redis 缓存连接
    - 交易所 API 连接
    
    Returns:
        JSONResponse: 健康状态信息
        - status: "healthy" 或 "degraded"
        - components: 各组件状态详情
        
    Status Codes:
        - 200: 所有关键组件健康
        - 503: 任何关键组件不健康
        
    Example Response:
        ```json
        {
            "status": "healthy",
            "components": {
                "postgres": "ok",
                "redis": "ok",
                "exchanges": {
                    "binance": "ok",
                    "okx": "ok"
                }
            }
        }
        ```
    """
    # 从 app.state 获取数据库实例
    db = request.app.state.db
    
    # 检查各组件状态
    postgres_ok = await db.health_check()
    redis_ok = await cache.health_check()
    
    # 检查交易所连接状态
    exchange_status: dict[str, str] = {}
    for exchange_id, client in clients.items():
        try:
            is_healthy = await client.health_check()
            exchange_status[exchange_id] = "ok" if is_healthy else "error"
        except Exception:
            exchange_status[exchange_id] = "error"
    
    # 构建组件状态
    components = {
        "postgres": "ok" if postgres_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "exchanges": exchange_status,
    }
    
    # 计算整体状态
    # 关键组件：PostgreSQL 和 Redis
    # 交易所连接不影响整体健康状态（可以降级运行）
    overall = "healthy" if postgres_ok and redis_ok else "degraded"
    
    # 返回响应
    status_code = 200 if overall == "healthy" else 503
    
    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "components": components,
        }
    )
