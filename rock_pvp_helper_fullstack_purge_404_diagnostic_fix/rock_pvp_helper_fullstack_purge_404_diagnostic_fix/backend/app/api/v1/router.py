"""
API v1 路由聚合模块。

按功能模块挂载接口，保持 URL 结构稳定，便于前端逐步接入。
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin_battles,
    battles,
    candidates,
    data_updates,
    effects,
    elves,
    health,
    natures,
    player_builds,
    skills,
)

router = APIRouter()

router.include_router(health.router, tags=["health"])
router.include_router(elves.router, prefix="/elves", tags=["elves"])
router.include_router(skills.router, prefix="/skills", tags=["skills"])
router.include_router(natures.router, prefix="/natures", tags=["natures"])
router.include_router(effects.router, prefix="/effects", tags=["effects"])
router.include_router(player_builds.router, prefix="/player-builds", tags=["player-builds"])
router.include_router(battles.router, prefix="/battles", tags=["battles"])
router.include_router(candidates.router, prefix="/candidates", tags=["candidates"])
router.include_router(data_updates.router, prefix="/admin/data-updates", tags=["admin-data-updates"])
router.include_router(admin_battles.router, prefix="/admin/battles", tags=["admin-battles"])
