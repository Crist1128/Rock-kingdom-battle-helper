"""
API v1 路由聚合模块。

本模块聚合 v1 版本的所有 API 端点路由，按功能模块分组：
- health: 健康检查
- elves: 精灵相关
- skills: 技能相关
- effects: 状态效果相关
- battles: 战斗相关
"""

from fastapi import APIRouter

from app.api.v1.endpoints import battles, effects, elves, health, skills

# 创建 v1 版本路由实例
router = APIRouter()

# 挂载各功能模块路由
router.include_router(health.router, tags=["health"])  # 健康检查
router.include_router(elves.router, prefix="/elves", tags=["elves"])  # 精灵管理
router.include_router(skills.router, prefix="/skills", tags=["skills"])  # 技能管理
router.include_router(effects.router, prefix="/effects", tags=["effects"])  # 状态效果管理
router.include_router(battles.router, prefix="/battles", tags=["battles"])  # 战斗管理
