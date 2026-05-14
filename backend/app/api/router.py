"""
API 路由聚合模块。

本模块聚合所有版本的 API 路由，统一挂载到 /api 路径下。
当前包含 v1 版本路由，未来可在此添加 v2、v3 等新版路由。
"""

from fastapi import APIRouter

from app.api.v1.router import router as v1_router

# 创建主 API 路由实例
api_router = APIRouter()

# 挂载 v1 版本路由，前缀为 /api/v1
api_router.include_router(v1_router, prefix="/v1")
