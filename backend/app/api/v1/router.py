"""
API v1 路由聚合模块。

按功能模块挂载接口，保持 URL 结构稳定，便于前端逐步接入。
"""

from fastapi import APIRouter

from app.api.v1.endpoints import battles, candidates, effects, elves, health, player_builds, skills

router = APIRouter()

router.include_router(health.router, tags=["health"])
router.include_router(elves.router, prefix="/elves", tags=["elves"])
router.include_router(skills.router, prefix="/skills", tags=["skills"])
router.include_router(effects.router, prefix="/effects", tags=["effects"])
router.include_router(player_builds.router, prefix="/player-builds", tags=["player-builds"])
router.include_router(battles.router, prefix="/battles", tags=["battles"])
router.include_router(candidates.router, prefix="/candidates", tags=["candidates"])
