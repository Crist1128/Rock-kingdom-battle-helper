"""敌方面板实时估计 Schema。"""

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.player_build import IndividualTalentInput


class EnemyDefaultConfigInput(BaseModel):
    """玩家为未知敌方面板选择的默认展示配置。"""

    preset: str = Field(default="custom", description="默认配置预设标识")
    nature_id: str = Field(..., description="性格 ID")
    individual_talent_distribution: IndividualTalentInput = Field(
        ...,
        description="六维显示个体资质",
    )


class EnemyPanelEstimateOut(BaseModel):
    """敌方面板估计档案输出。"""

    estimate_id: str = Field(..., description="估计档案 ID")
    battle_id: str = Field(..., description="战斗 ID")
    battle_elf_state_id: str = Field(..., description="敌方战斗精灵状态 ID")
    elf_id: str = Field(..., description="敌方精灵 ID")
    default_config: dict[str, Any] | None = Field(default=None, description="玩家默认配置")
    default_panel: dict[str, Any] | None = Field(default=None, description="默认配置面板")
    estimated_panel: dict[str, Any] | None = Field(default=None, description="当前展示估计面板")
    stat_constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="属性推导约束",
    )
    confidence: dict[str, Any] = Field(default_factory=dict, description="各属性置信状态")
    unknown_factors: list[str] = Field(default_factory=list, description="未知因素")
    confirmed_skill_ids: list[str] = Field(default_factory=list, description="已确认技能 ID")
    evidence_summary: list[dict[str, Any]] = Field(
        default_factory=list,
        description="最近估计证据摘要",
    )
    updated_by_event_id: str | None = Field(default=None, description="最近更新事件 ID")


class EnemyPanelEstimateEvidenceOut(BaseModel):
    """敌方面板估计 evidence 输出。"""

    evidence_id: str = Field(..., description="证据 ID")
    estimate_id: str = Field(..., description="估计档案 ID")
    battle_id: str = Field(..., description="战斗 ID")
    source_event_id: str = Field(..., description="来源事件 ID")
    observation_type: str = Field(..., description="观测类型")
    inferred_stats: dict[str, Any] | None = Field(default=None, description="本次推导属性")
    constraint_delta: dict[str, Any] | None = Field(default=None, description="约束变化")
    formula_context: dict[str, Any] | None = Field(default=None, description="公式上下文")
    explanation: dict[str, Any] | None = Field(default=None, description="面向前端展示的推导解释")
    unknown_factors: list[str] = Field(default_factory=list, description="未知因素")
    conflict: dict[str, Any] | None = Field(default=None, description="冲突信息")
    confidence: str | None = Field(default=None, description="本次推导置信状态")
