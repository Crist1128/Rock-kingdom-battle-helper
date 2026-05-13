from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.battle import Battle
from app.models.event import BattleEvent
from app.schemas.battle import BattleCreate, BattleOut, BattleStateOut
from app.schemas.event import BattleEventCreate, BattleEventOut
from app.services.battle_service import BattleService

router = APIRouter()


@router.post("", response_model=BattleOut, status_code=201)
def create_battle(payload: BattleCreate, db: Session = Depends(get_db)) -> Battle:
    return BattleService(db).create_battle(payload)


@router.get("/{battle_id}", response_model=BattleOut)
def get_battle(battle_id: str, db: Session = Depends(get_db)) -> Battle:
    battle = db.get(Battle, battle_id)
    if battle is None or battle.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Battle not found")
    return battle


@router.get("/{battle_id}/state", response_model=BattleStateOut)
def get_battle_state(battle_id: str, db: Session = Depends(get_db)) -> BattleStateOut:
    battle = db.get(Battle, battle_id)
    if battle is None or battle.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Battle not found")
    return BattleService(db).get_state(battle)


@router.post("/{battle_id}/events", response_model=BattleEventOut, status_code=201)
def create_battle_event(
    battle_id: str,
    payload: BattleEventCreate,
    db: Session = Depends(get_db),
) -> BattleEvent:
    battle = db.get(Battle, battle_id)
    if battle is None or battle.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Battle not found")
    return BattleService(db).create_event(battle_id, payload)


@router.get("/{battle_id}/events", response_model=list[BattleEventOut])
def list_battle_events(battle_id: str, db: Session = Depends(get_db)) -> list[BattleEvent]:
    battle = db.get(Battle, battle_id)
    if battle is None or battle.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Battle not found")
    stmt = select(BattleEvent).where(BattleEvent.battle_id == battle_id).order_by(
        BattleEvent.turn_number, BattleEvent.created_at
    )
    return list(db.scalars(stmt).all())
