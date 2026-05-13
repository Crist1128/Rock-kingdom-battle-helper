from pydantic import BaseModel

from app.schemas.common import ORMBase


class BattleEventCreate(BaseModel):
    turn_number: int
    event_type: str
    actor_side: str | None = None
    actor_elf_id: str | None = None
    target_side: str | None = None
    target_elf_id: str | None = None
    skill_id: str | None = None
    skill_confirmed: bool = False
    snapshot_id: str | None = None
    source: str = "manual_input"
    recognition_confidence: float | None = None
    manual_override: bool = False
    payload_json: str | None = None
    notes: str | None = None


class BattleEventOut(ORMBase):
    event_id: str
    battle_id: str
    turn_number: int
    event_type: str
    actor_side: str | None = None
    actor_elf_id: str | None = None
    target_side: str | None = None
    target_elf_id: str | None = None
    skill_id: str | None = None
    skill_confirmed: bool
    snapshot_id: str | None = None
    source: str
    recognition_confidence: float | None = None
    manual_override: bool
    payload_json: str | None = None
    notes: str | None = None
