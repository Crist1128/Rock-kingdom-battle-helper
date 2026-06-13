"""实时面板估计使用的通用观察事件输入。"""

from typing import Any

from pydantic import BaseModel, Field

from app.inference.observation_types import ObservationType


class ObservationEventInput(BaseModel):
    """Observation API、伤害事件和事件重放共用的观察事件输入。"""

    battle_id: str
    enemy_elf_id: str
    event_id: str
    observation_type: ObservationType
    observed_value: int | float | str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    event_weight: float | None = None
