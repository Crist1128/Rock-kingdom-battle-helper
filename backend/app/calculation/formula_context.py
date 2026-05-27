"""伤害公式上下文与结果模型。

第二里程碑开始引入“最小可用普通攻击伤害”计算。这里的模型仍保持向后兼容：
旧的 DamageEventService 只提供事件 ID、双方 ID、观测伤害等粗字段时，DamageCalculator 会
返回 ``formula_unavailable``；只有上下文具备攻防面板、技能类别和威力等必要字段时才计算。
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class PanelStats(BaseModel):
    """六维面板属性。

    候选反推时，敌方字段来自 BuildCandidate；己方字段可来自 BattleElfState 或前端输入。
    """

    hp: int
    physical_attack: int
    physical_defense: int
    magic_attack: int
    magic_defense: int
    speed: int


class DamageFormulaContext(BaseModel):
    """伤害公式上下文。

    字段分为三类：
    1. 事件追踪字段，用于把结果写回 DamageEvent / evidence；
    2. 公式输入字段，用于普通攻击伤害计算；
    3. 观测字段，用于 DamageMatcher 比较玩家录入值。
    """

    # 事件追踪字段。为兼容旧调用，除 battle_id 外均允许为空。
    battle_id: str
    damage_event_id: str | None = None
    battle_event_id: str | None = None
    snapshot_id: str | None = None
    formula_type: str = "attack"

    attacker_side: str | None = None
    attacker_elf_id: str | None = None
    defender_side: str | None = None
    defender_elf_id: str | None = None
    skill_id: str | None = None
    skill_element_type: str | None = None
    attacker_element_types: list[str] = Field(default_factory=list)
    defender_element_types: list[str] = Field(default_factory=list)
    damage_display_type: str = "single_damage"

    # 面板与技能基础信息。
    attacker_panel_stats: PanelStats | None = None
    defender_panel_stats: PanelStats | None = None
    defender_max_hp: int | None = None
    skill_category: str | None = None  # physical | magic
    base_power: Decimal | int | float | None = None
    display_power: Decimal | int | float | None = None

    # 已解析公式修正项。RuleResolver 尚未实现前，由 payload 或测试直接提供。
    response_multiplier: Decimal | int | float = Decimal("1")
    flat_power_bonus: Decimal | int | float = Decimal("0")
    power_multiplier: Decimal | int | float = Decimal("1")
    stat_stage_multiplier: Decimal | int | float = Decimal("1")
    stab_multiplier: Decimal | int | float = Decimal("1")
    type_multiplier: Decimal | int | float = Decimal("1")
    weather_multiplier: Decimal | int | float = Decimal("1")
    unstable_multiplier: Decimal | int | float = Decimal("1")
    damage_reductions: list[Decimal | int | float] = Field(default_factory=list)
    hit_count: int = 1

    # 观测字段。
    observed_damage_value: int | None = None
    observed_hp_percent_delta: float | None = None

    # 原始快照与说明。
    snapshot_payload: dict[str, Any] | list[Any] | None = None
    notes: str | None = None
    unknown_factors: list[str] = Field(default_factory=list)
    rule_resolution_enabled: bool = False
    rule_resolution_details: dict[str, Any] = Field(default_factory=dict)


class CalculationPlaceholderResult(BaseModel):
    """伤害计算结果。

    历史上该类只表示占位结果。为保持兼容，类名暂不变，但现在也承载 calculated 结果。
    """

    status: str = "formula_unavailable"
    formula_type: str = "attack"
    damage_value: int | None = None
    damage_range: tuple[int, int] | None = None
    confidence: float = 0.0
    missing_parts: list[str] = Field(default_factory=list)
    unknown_factors: list[str] = Field(default_factory=list)
    context_id: str | None = None
    message: str = "伤害公式尚未确认，本次只记录事实，不执行候选排除。"
    explanation: dict[str, Any] = Field(default_factory=dict)
