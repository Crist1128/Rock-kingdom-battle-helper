"""
健康检查端点模块。

提供系统健康状态检查接口，用于：
- 服务状态监控
- 负载均衡健康检查
- 部署验证
"""

from fastapi import APIRouter

# 创建路由实例
router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, str]:
    """
    健康检查端点。

    返回服务的健康状态，用于确认服务是否正常运行。

    Returns:
        dict[str, str]: 包含状态信息的字典，status 为 "ok" 表示正常

    Example:
        GET /api/v1/health
        Response: {"status": "ok"}
    """
    return {"status": "ok"}
