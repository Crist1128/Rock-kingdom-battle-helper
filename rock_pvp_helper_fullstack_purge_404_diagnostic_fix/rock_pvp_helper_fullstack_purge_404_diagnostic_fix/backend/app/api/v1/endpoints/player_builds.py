"""
己方配置管理端点。

用于维护玩家提前录入的己方完整配置。准备阶段录入己方阵容时，必须引用这里
创建的 build_id。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.player_build import (
    PlayerElfBuildCreate,
    PlayerElfBuildOut,
    PlayerElfBuildSkillReplace,
    PlayerElfBuildUpdate,
)
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


@router.put("/{build_id}", response_model=PlayerElfBuildOut)
def update_player_build(
    build_id: str,
    payload: PlayerElfBuildUpdate,
    db: Session = Depends(get_db),
) -> PlayerElfBuildOut:
    """
    更新己方精灵配置。

    前端编辑页提交完整配置后，后端会重新计算面板属性，并按 skill_ids 顺序
    重建技能槽。这样可以保证六维个体资质、性格和技能槽排序始终一致。
    """
    try:
        return PlayerElfBuildService(db).update_build(build_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{build_id}/skills", response_model=PlayerElfBuildOut)
def replace_player_build_skills(
    build_id: str,
    payload: PlayerElfBuildSkillReplace,
    db: Session = Depends(get_db),
) -> PlayerElfBuildOut:
    """仅替换技能槽顺序，适合前端拖拽排序后的轻量保存。"""
    try:
        return PlayerElfBuildService(db).replace_build_skills(build_id, payload.skill_ids)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{build_id}", response_model=PlayerElfBuildOut)
def get_player_build(build_id: str, db: Session = Depends(get_db)) -> PlayerElfBuildOut:
    """获取单个己方配置。"""
    try:
        return PlayerElfBuildService(db).get_build(build_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{build_id}", status_code=204)
def delete_player_build(
    build_id: str,
    db: Session = Depends(get_db),
) -> None:
    """软删除己方配置，供前端配置管理页调用。"""
    try:
        PlayerElfBuildService(db).delete_build(build_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
