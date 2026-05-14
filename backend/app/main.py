"""
FastAPI 应用主入口模块。

本模块负责创建和配置 FastAPI 应用实例，包括：
- 应用元数据配置（标题、版本、描述）
- CORS 跨域中间件配置
- API 路由注册
- 根路由定义
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings


def create_app() -> FastAPI:
    """
    创建并配置 FastAPI 应用实例。

    Returns:
        FastAPI: 配置完成的 FastAPI 应用实例
    """
    # 创建 FastAPI 应用实例，配置基础元数据
    app = FastAPI(
        title=settings.app_name,  # 应用标题，从配置中读取
        version="0.1.0",  # 应用版本号
        description="洛克王国世界 PVP 战斗信息获取与敌方配置推算系统 API",  # 应用描述
    )

    # 添加 CORS 跨域中间件，允许前端应用访问 API
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,  # 允许的跨域来源列表
        allow_credentials=True,  # 允许携带凭证（如 Cookie）
        allow_methods=["*"],  # 允许所有 HTTP 方法
        allow_headers=["*"],  # 允许所有请求头
    )

    # 注册 API 路由，所有路由以 /api 为前缀
    app.include_router(api_router, prefix="/api")

    # 定义根路由，返回应用基本信息
    @app.get("/")
    def root() -> dict[str, str]:
        """
        根路由处理函数。

        Returns:
            dict[str, str]: 包含应用名称和 API 文档链接的字典
        """
        return {"message": settings.app_name, "docs": "/docs"}

    return app


# 创建应用实例，供 Uvicorn 等服务器启动时使用
app = create_app()
