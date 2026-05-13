from fastapi import APIRouter

from app.api.v1.endpoints import battles, effects, elves, health, skills

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(elves.router, prefix="/elves", tags=["elves"])
router.include_router(skills.router, prefix="/skills", tags=["skills"])
router.include_router(effects.router, prefix="/effects", tags=["effects"])
router.include_router(battles.router, prefix="/battles", tags=["battles"])
