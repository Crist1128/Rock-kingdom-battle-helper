"""
战斗管理端点模块。

提供手动输入 MVP 所需的战斗接口：创建战斗、录入阵容、进入战斗、切换精灵、
记录通用事件、记录伤害事件和查询战斗状态。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.battle import Battle
from app.models.event import BattleEvent
from app.schemas.battle import (
    BattleCreate,
    BattleOut,
    BattleStateOut,
    LineupInput,
    LineupOut,
    StartBattleInput,
    SwitchElfInput,
)
from app.schemas.event import (
    BattleEventCreate,
    BattleEventOut,
    DamageEventCreate,
    DamageEventCreateResult,
)
from app.services.battle_service import BattleService
from app.services.damage_event_service import DamageEventService

router = APIRouter()


@router.post("", response_model=BattleOut, status_code=201)
def create_battle(payload: BattleCreate, db: Session = Depends(get_db)) -> Battle:
    """创建新战斗，初始阶段为 preparation。"""
    return BattleService(db).create_battle(payload)


@router.get("/{battle_id}", response_model=BattleOut)
def get_battle(battle_id: str, db: Session = Depends(get_db)) -> Battle:
    """获取战斗基础信息。"""
    try:
        return BattleService(db).require_battle(battle_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{battle_id}/lineup", response_model=LineupOut)
def setup_lineup(
    battle_id: str,
    payload: LineupInput,
    db: Session = Depends(get_db),
) -> LineupOut:
    """
    录入双方阵容。

    己方精灵必须带 build_id，敌方只需要 elf_id。提交后会自动生成敌方候选配置。
    """
    try:
        return BattleService(db).setup_lineup(battle_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{battle_id}/start", response_model=BattleOut)
def start_battle(
    battle_id: str,
    payload: StartBattleInput,
    db: Session = Depends(get_db),
) -> Battle:
    """确认双方首发并进入 battle 阶段。"""
    try:
        return BattleService(db).start_battle(
            battle_id,
            self_active_elf_id=payload.self_active_elf_id,
            enemy_active_elf_id=payload.enemy_active_elf_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{battle_id}/switch", response_model=BattleOut)
def switch_elf(
    battle_id: str,
    payload: SwitchElfInput,
    db: Session = Depends(get_db),
) -> Battle:
    """切换当前上场精灵，并执行状态切换清除规则。"""
    try:
        return BattleService(db).switch_elf(battle_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{battle_id}/state", response_model=BattleStateOut)
def get_battle_state(battle_id: str, db: Session = Depends(get_db)) -> BattleStateOut:
    """获取战斗完整状态。"""
    try:
        battle = BattleService(db).require_battle(battle_id)
        return BattleService(db).get_state(battle)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{battle_id}/events", response_model=BattleEventOut, status_code=201)
def create_battle_event(
    battle_id: str,
    payload: BattleEventCreate,
    db: Session = Depends(get_db),
) -> BattleEvent:
    """创建通用战斗事件。"""
    try:
        return BattleService(db).create_event(battle_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{battle_id}/damage-events", response_model=DamageEventCreateResult, status_code=201)
def create_damage_event(
    battle_id: str,
    payload: DamageEventCreate,
    db: Session = Depends(get_db),
) -> DamageEventCreateResult:
    """
    创建伤害事件。

    当前不会执行真实伤害公式，也不会排除候选配置；响应中的 inference_result
    会明确返回 formula_unavailable。
    """
    try:
        return DamageEventService(db).create_damage_event(battle_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{battle_id}/events", response_model=list[BattleEventOut])
def list_battle_events(battle_id: str, db: Session = Depends(get_db)) -> list[BattleEvent]:
    """获取战斗事件列表，按回合和创建时间排序。"""
    try:
        BattleService(db).require_battle(battle_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    stmt = select(BattleEvent).where(BattleEvent.battle_id == battle_id).order_by(
        BattleEvent.turn_number,
        BattleEvent.created_at,
    )
    return list(db.scalars(stmt).all())
