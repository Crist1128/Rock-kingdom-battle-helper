from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.static import EffectDefinition
from app.schemas.static import EffectDefinitionOut

router = APIRouter()


@router.get("", response_model=list[EffectDefinitionOut])
def list_effects(
    category: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[EffectDefinition]:
    stmt = select(EffectDefinition).where(EffectDefinition.deleted_at.is_(None))
    if category:
        stmt = stmt.where(EffectDefinition.category == category)
    if q:
        stmt = stmt.where(EffectDefinition.effect_name.contains(q))
    stmt = stmt.order_by(EffectDefinition.display_priority, EffectDefinition.effect_name).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


@router.get("/{effect_id}", response_model=EffectDefinitionOut)
def get_effect(effect_id: str, db: Session = Depends(get_db)) -> EffectDefinition:
    effect = db.get(EffectDefinition, effect_id)
    if effect is None or effect.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Effect not found")
    return effect
