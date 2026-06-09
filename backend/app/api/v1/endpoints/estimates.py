"""敌方面板实时估计端点。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.estimate import (
    EnemyDefaultConfigInput,
    EnemyPanelEstimateEvidenceOut,
    EnemyPanelEstimateOut,
)
from app.services.battle_service import BattleService
from app.services.estimate_service import EstimateService

router = APIRouter()


@router.get("/{battle_id}/{elf_id}", response_model=EnemyPanelEstimateOut)
def get_enemy_panel_estimate(
    battle_id: str,
    elf_id: str,
    db: Session = Depends(get_db),
) -> EnemyPanelEstimateOut:
    """获取某只敌方精灵的实时面板估计。"""
    try:
        BattleService(db).require_battle(battle_id)
        return EstimateService(db).get_estimate(battle_id, elf_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{battle_id}/{elf_id}/default-config", response_model=EnemyPanelEstimateOut)
def update_enemy_default_config(
    battle_id: str,
    elf_id: str,
    payload: EnemyDefaultConfigInput,
    db: Session = Depends(get_db),
) -> EnemyPanelEstimateOut:
    """更新玩家为未知敌方面板选择的默认展示配置。"""
    try:
        BattleService(db).require_battle(battle_id)
        return EstimateService(db).update_default_config(battle_id, elf_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{battle_id}/{elf_id}/evidence",
    response_model=list[EnemyPanelEstimateEvidenceOut],
)
def list_enemy_panel_estimate_evidence(
    battle_id: str,
    elf_id: str,
    limit: int = Query(default=50, ge=1, le=200, description="返回证据数量上限"),
    db: Session = Depends(get_db),
) -> list[EnemyPanelEstimateEvidenceOut]:
    """获取某只敌方精灵的实时估计证据列表。"""
    try:
        BattleService(db).require_battle(battle_id)
        return EstimateService(db).list_evidence(battle_id, elf_id, limit=limit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

