"""
状态效果管理端点模块。

包括两类接口：
- /effects：查询静态状态定义；
- /effects/instances：手动管理战斗中的状态实例。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.static import EffectDefinition
from app.schemas.effect import EffectApplyInput, EffectInstanceOut, EffectRemoveInput
from app.schemas.static import EffectDefinitionOut
from app.services.effect_service import BattleEffectService

router = APIRouter()


@router.get("", response_model=list[EffectDefinitionOut])
def list_effects(
    category: str | None = Query(default=None, description="按 category 筛选"),
    owner_scope: str | None = Query(default=None, description="按 owner_scope 筛选"),
    clear_on_switch: bool | None = Query(default=None, description="按切换是否清除筛选"),
    q: str | None = Query(default=None, description="按 effect_name 模糊搜索"),
    limit: int = Query(default=50, ge=1, le=500, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
) -> list[EffectDefinition]:
    """获取状态效果定义列表，可按分类、归属范围和切换清除规则筛选。"""
    stmt = select(EffectDefinition).where(EffectDefinition.deleted_at.is_(None))
    if category:
        stmt = stmt.where(EffectDefinition.category == category)
    if owner_scope:
        stmt = stmt.where(EffectDefinition.owner_scope == owner_scope)
    if clear_on_switch is not None:
        stmt = stmt.where(EffectDefinition.clear_on_switch.is_(clear_on_switch))
    if q:
        stmt = stmt.where(EffectDefinition.effect_name.contains(q))
    stmt = (
        stmt.order_by(EffectDefinition.display_priority, EffectDefinition.effect_name)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


@router.get("/{effect_id}", response_model=EffectDefinitionOut)
def get_effect(effect_id: str, db: Session = Depends(get_db)) -> EffectDefinition:
    """获取单个状态效果定义。"""
    effect = db.get(EffectDefinition, effect_id)
    if effect is None or effect.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Effect not found")
    return effect


@router.post("/instances", response_model=EffectInstanceOut, status_code=201)
def apply_effect_instance(
    payload: EffectApplyInput,
    db: Session = Depends(get_db),
) -> EffectInstanceOut:
    """手动施加战斗状态实例。"""
    try:
        return BattleEffectService(db).apply_effect(payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/instances/{instance_id}", response_model=EffectInstanceOut)
def remove_effect_instance(
    instance_id: str,
    payload: EffectRemoveInput | None = None,
    db: Session = Depends(get_db),
) -> EffectInstanceOut:
    """手动移除战斗状态实例。"""
    try:
        return BattleEffectService(db).remove_effect(
            instance_id,
            payload or EffectRemoveInput(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
