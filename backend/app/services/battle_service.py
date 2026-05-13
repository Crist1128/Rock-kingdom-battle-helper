from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.battle import Battle, BattleElfState
from app.models.effect import BattleEffectInstance
from app.models.event import BattleEvent
from app.schemas.battle import BattleCreate, BattleStateOut
from app.schemas.event import BattleEventCreate


class BattleService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_battle(self, payload: BattleCreate) -> Battle:
        battle = Battle(
            battle_id=f"battle_{uuid4().hex}",
            battle_name=payload.battle_name,
            notes=payload.notes,
            phase="preparation",
            turn_number=0,
        )
        self.db.add(battle)
        self.db.commit()
        self.db.refresh(battle)
        return battle

    def get_state(self, battle: Battle) -> BattleStateOut:
        elves = self.db.scalars(
            select(BattleElfState).where(BattleElfState.battle_id == battle.battle_id)
        ).all()
        effects = self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle.battle_id,
                BattleEffectInstance.is_active.is_(True),
            )
        ).all()
        return BattleStateOut(
            battle=battle,
            elves=[self._model_to_dict(item) for item in elves],
            active_effects=[self._model_to_dict(item) for item in effects],
            latest_snapshot_id=battle.current_snapshot_id,
        )

    def create_event(self, battle_id: str, payload: BattleEventCreate) -> BattleEvent:
        event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=payload.turn_number,
            event_type=payload.event_type,
            actor_side=payload.actor_side,
            actor_elf_id=payload.actor_elf_id,
            target_side=payload.target_side,
            target_elf_id=payload.target_elf_id,
            skill_id=payload.skill_id,
            skill_confirmed=payload.skill_confirmed,
            snapshot_id=payload.snapshot_id,
            source=payload.source,
            recognition_confidence=payload.recognition_confidence,
            manual_override=payload.manual_override,
            payload_json=payload.payload_json,
            notes=payload.notes,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    @staticmethod
    def _model_to_dict(model: object) -> dict:
        return {column.name: getattr(model, column.name) for column in model.__table__.columns}  # type: ignore[attr-defined]
