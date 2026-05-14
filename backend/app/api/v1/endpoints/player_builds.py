"""
己方配置管理端点。

用于维护玩家提前录入的己方完整配置。准备阶段录入己方阵容时，必须引用这里
创建的 build_id。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.player_build import PlayerElfBuildCreate, PlayerElfBuildOut
from app.services.player_build_service import PlayerElfBuildService

router = APIRouter()


@router.post("", response_model=PlayerElfBuildOut, status_code=201)
def create_player_build(
    payload: PlayerElfBuildCreate,
    db: Session = Depends(get_db),
) -> PlayerElfBuildOut:
    """创建己方精灵配置，并自动计算面板属性。"""
    try:
        return PlayerElfBuildService(db).create_build(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[PlayerElfBuildOut])
def list_player_builds(
    elf_id: str | None = Query(default=None, description="按精灵 ID 筛选"),
    db: Session = Depends(get_db),
) -> list[PlayerElfBuildOut]:
    """列出己方配置。"""
    return PlayerElfBuildService(db).list_builds(elf_id=elf_id)


@router.get("/{build_id}", response_model=PlayerElfBuildOut)
def get_player_build(build_id: str, db: Session = Depends(get_db)) -> PlayerElfBuildOut:
    """获取单个己方配置。"""
    try:
        return PlayerElfBuildService(db).get_build(build_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
