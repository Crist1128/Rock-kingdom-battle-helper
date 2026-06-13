"""观察事件 API Schema。"""

from typing import Any

from pydantic import BaseModel, Field

from app.inference.observation_types import ObservationType


class ObservationCreate(BaseModel):
    """提交一条观察事件的请求体。"""

    enemy_elf_id: str = Field(..., min_length=1, description="被观察的敌方精灵 ID")
    event_id: str | None = Field(
        default=None,
        description="观察事件 ID；不传时后端自动生成 observation_<uuid>",
    )
    observation_type: ObservationType = Field(..., description="观察事件类型")
    observed_value: int | float | str | None = Field(
        default=None,
        description="观察到的核心数值或枚举值，例如伤害数字、扣血百分比、self_first",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="观察上下文；不同 observation_type 使用不同键集合",
    )
    event_weight: float | None = Field(
        default=None,
        description="本事件的估计权重；不传时由实时估计服务使用默认权重",
    )


class ObservationProcessResult(BaseModel):
    """观察事件处理结果。"""

    status: str
    battle_id: str
    enemy_elf_id: str
    event_id: str
    observation_type: str
    estimate_id: str | None = None
    inferred_stat_count: int = 0
    affected_stats: list[str] = Field(default_factory=list)
    unknown_factor_count: int = 0
