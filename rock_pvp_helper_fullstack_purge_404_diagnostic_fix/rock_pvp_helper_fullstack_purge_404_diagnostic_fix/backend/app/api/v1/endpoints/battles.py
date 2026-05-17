"""
战斗管理端点模块。

提供手动输入 MVP 所需的战斗接口：创建战斗、录入阵容、进入战斗、切换精灵、
记录通用事件、记录伤害事件和查询战斗状态。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.battle import Battle
from app.models.effect import BattleEffectSnapshot
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
from app.schemas.effect import BattleEffectSnapshotOut
from app.schemas.event import (
    BattleEventCorrectInput,
    BattleEventCreate,
    BattleEventOut,
    BattleEventVoidInput,
    BattleReplayResult,
    BattleTimelineTurnOut,
    DamageEventCreate,
    DamageEventCreateResult,
    ResourceChangeEventCreate,
    ResourceChangeEventCreateResult,
)
from app.services.battle_service import BattleService
from app.services.damage_event_service import DamageEventService
from app.services.resource_event_service import ResourceEventService

router = APIRouter()


@router.post("", response_model=BattleOut, status_code=201)
def create_battle(payload: BattleCreate, db: Session = Depends(get_db)) -> Battle:
    """创建新战斗，初始阶段为 preparation。"""
    return BattleService(db).create_battle(payload)


@router.get("", response_model=list[BattleOut])
def list_battles(
    phase: str | None = Query(default=None, description="按阶段筛选"),
    include_archived: bool = Query(default=False, description="未指定 phase 时是否包含已归档战斗"),
    limit: int = Query(default=50, ge=1, le=200, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
) -> list[Battle]:
    """列出战斗记录。

    默认不返回 archived，用于首页“最近战斗”列表；需要查看归档记录时
    可传 include_archived=true，或显式传 phase=archived。
    """
    return BattleService(db).list_battles(
        phase=phase,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )


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


@router.post("/{battle_id}/finish", response_model=BattleOut)
def finish_battle(battle_id: str, db: Session = Depends(get_db)) -> Battle:
    """结束战斗，保留事件和候选数据。"""
    try:
        return BattleService(db).finish_battle(battle_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{battle_id}/archive", response_model=BattleOut)
def archive_battle(battle_id: str, db: Session = Depends(get_db)) -> Battle:
    """归档战斗，作为历史记录保留。"""
    try:
        return BattleService(db).archive_battle(battle_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@router.post(
    "/{battle_id}/resource-events",
    response_model=ResourceChangeEventCreateResult,
    status_code=201,
)
def create_resource_event(
    battle_id: str,
    payload: ResourceChangeEventCreate,
    db: Session = Depends(get_db),
) -> ResourceChangeEventCreateResult:
    """
    创建生命 / 能量变化事件。

    用于手动记录治疗、能量获得、能量消耗等事实。伤害导致的生命变化由
    /damage-events 自动补充 ResourceChangeEvent。
    """
    try:
        return ResourceEventService(db).create_resource_change_event(battle_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{battle_id}/timeline", response_model=list[BattleTimelineTurnOut])
def get_battle_timeline(
    battle_id: str,
    db: Session = Depends(get_db),
) -> list[BattleTimelineTurnOut]:
    """获取按回合聚合的战斗事件时间线。"""
    try:
        return BattleService(db).get_timeline(battle_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{battle_id}/snapshots/{snapshot_id}", response_model=BattleEffectSnapshotOut)
def get_battle_snapshot(
    battle_id: str,
    snapshot_id: str,
    db: Session = Depends(get_db),
) -> BattleEffectSnapshot:
    """读取某个状态快照详情。"""
    try:
        BattleService(db).require_battle(battle_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    snapshot = db.get(BattleEffectSnapshot, snapshot_id)
    if snapshot is None or snapshot.battle_id != battle_id or snapshot.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot


@router.post("/{battle_id}/events/{event_id}/void", response_model=BattleEventOut)
def void_battle_event(
    battle_id: str,
    event_id: str,
    payload: BattleEventVoidInput,
    db: Session = Depends(get_db),
) -> BattleEvent:
    """作废历史事件。当前不会自动重放重算。"""
    try:
        return BattleService(db).void_event(battle_id, event_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{battle_id}/events/{event_id}/correct", response_model=BattleEventOut)
def correct_battle_event(
    battle_id: str,
    event_id: str,
    payload: BattleEventCorrectInput,
    db: Session = Depends(get_db),
) -> BattleEvent:
    """创建修正事件。当前不会自动重放重算。"""
    try:
        return BattleService(db).correct_event(battle_id, event_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{battle_id}/replay-from/{event_id}", response_model=BattleReplayResult)
def replay_battle_from_event(
    battle_id: str,
    event_id: str,
    db: Session = Depends(get_db),
) -> BattleReplayResult:
    """从某事件开始重放的占位接口。"""
    try:
        return BattleService(db).replay_from_event(battle_id, event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{battle_id}/events", response_model=list[BattleEventOut])
def list_battle_events(battle_id: str, db: Session = Depends(get_db)) -> list[BattleEvent]:
    """获取战斗事件列表，按回合和创建时间排序。"""
    try:
        BattleService(db).require_battle(battle_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    stmt = select(BattleEvent).where(
        BattleEvent.battle_id == battle_id,
        BattleEvent.is_voided.is_(False),
    ).order_by(
        BattleEvent.turn_number,
        BattleEvent.action_order,
        BattleEvent.created_at,
    )
    return list(db.scalars(stmt).all())
