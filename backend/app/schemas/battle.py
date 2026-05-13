from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMBase


class BattleCreate(BaseModel):
    battle_name: str | None = Field(default=None, description="战斗名称，可为空")
    notes: str | None = None


class BattleOut(ORMBase):
    battle_id: str
    battle_name: str | None = None
    phase: str
    turn_number: int
    self_active_elf_id: str | None = None
    enemy_active_elf_id: str | None = None
    current_snapshot_id: str | None = None
    notes: str | None = None


class BattleStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    battle: BattleOut
    elves: list[dict] = Field(default_factory=list)
    active_effects: list[dict] = Field(default_factory=list)
    latest_snapshot_id: str | None = None


class LineupElfInput(BaseModel):
    side: str
    elf_id: str
    build_id: str | None = None
    is_active_elf: bool = False


class LineupInput(BaseModel):
    elves: list[LineupElfInput]
