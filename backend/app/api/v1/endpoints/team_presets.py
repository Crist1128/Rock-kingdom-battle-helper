"""
配队预设端点。

用于己方配置页维护 6 只精灵组成的配队，并在准备阶段快速填充己方或
敌方阵容。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.team_preset import TeamPresetCreate, TeamPresetOut, TeamPresetUpdate
from app.services.team_preset_service import TeamPresetService

router = APIRouter()


@router.post("", response_model=TeamPresetOut, status_code=201)
def create_team_preset(
    payload: TeamPresetCreate,
    db: Session = Depends(get_db),
) -> TeamPresetOut:
    """创建配队预设。"""
    try:
        return TeamPresetService(db).create_preset(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[TeamPresetOut])
def list_team_presets(
    side_usage: str | None = Query(default=None, description="按使用侧筛选：self/enemy/both"),
    source_type: str | None = Query(default=None, description="按来源筛选：custom/popular"),
    db: Session = Depends(get_db),
) -> list[TeamPresetOut]:
    """列出配队预设。"""
    try:
        return TeamPresetService(db).list_presets(
            side_usage=side_usage,
            source_type=source_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{preset_id}", response_model=TeamPresetOut)
def get_team_preset(preset_id: str, db: Session = Depends(get_db)) -> TeamPresetOut:
    """获取单个配队预设。"""
    try:
        return TeamPresetService(db).get_preset(preset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{preset_id}", response_model=TeamPresetOut)
def update_team_preset(
    preset_id: str,
    payload: TeamPresetUpdate,
    db: Session = Depends(get_db),
) -> TeamPresetOut:
    """更新配队预设，槽位采用整单替换。"""
    try:
        return TeamPresetService(db).update_preset(preset_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{preset_id}", status_code=204)
def delete_team_preset(preset_id: str, db: Session = Depends(get_db)) -> None:
    """软删除配队预设。"""
    try:
        TeamPresetService(db).delete_preset(preset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
