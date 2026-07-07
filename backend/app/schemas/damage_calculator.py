"""独立伤害计算器 API Schema。

该模块只描述独立计算器的输入输出，不参与战斗事件流写入。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class DamageCalculatorTalentInput(BaseModel):
    """六维个体资质输入。"""

    hp: int = Field(default=0, ge=0, le=10, description="生命个体资质")
    physical_attack: int = Field(default=0, ge=0, le=10, description="物攻个体资质")
    physical_defense: int = Field(default=0, ge=0, le=10, description="物防个体资质")
    magic_attack: int = Field(default=0, ge=0, le=10, description="魔攻个体资质")
    magic_defense: int = Field(default=0, ge=0, le=10, description="魔防个体资质")
    speed: int = Field(default=0, ge=0, le=10, description="速度个体资质")


class DamageCalculatorPanelInput(BaseModel):
    """手动指定的六维面板。"""

    hp: int = Field(..., gt=0, description="生命面板")
    physical_attack: int = Field(..., gt=0, description="物攻面板")
    physical_defense: int = Field(..., gt=0, description="物防面板")
    magic_attack: int = Field(..., gt=0, description="魔攻面板")
    magic_defense: int = Field(..., gt=0, description="魔防面板")
    speed: int = Field(..., gt=0, description="速度面板")


class DamageCalculatorParticipantInput(BaseModel):
    """计算参与方输入。"""

    elf_id: str = Field(..., description="精灵 ID")
    nature_id: str | None = Field(default=None, description="性格 ID；未提供面板时必填")
    individual_talent_distribution: DamageCalculatorTalentInput | None = Field(
        default=None,
        description="个体资质；未提供面板时使用，未填维度按 0 处理",
    )
    panel_stats: DamageCalculatorPanelInput | None = Field(
        default=None,
        description="手动面板；提供后优先使用，不再按性格资质重算",
    )


class DamageCalculatorModifierInput(BaseModel):
    """公式修正项输入。"""

    weather_multiplier: float | None = Field(default=None, gt=0, description="天气倍率")
    power_multiplier: float | None = Field(default=None, gt=0, description="威力倍率")
    flat_power_bonus: float | None = Field(default=None, description="固定威力修正")
    stat_stage_multiplier: float | None = Field(default=None, gt=0, description="能力倍率")
    stab_multiplier: float | None = Field(default=None, gt=0, description="本系倍率手动覆盖")
    type_multiplier: float | None = Field(default=None, ge=0, description="克制倍率手动覆盖")
    unstable_multiplier: float | None = Field(default=None, gt=0, description="额外不稳定倍率")
    damage_reductions: list[float] = Field(
        default_factory=list,
        description="减伤比例列表；例如 0.25 表示减少 25%",
    )
    hit_count: int | None = Field(default=None, ge=1, le=99, description="连击段数")
    defender_hp_percent: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="目标当前生命百分比，仅用于上下文展示",
    )
    condition_flags: dict[str, bool] = Field(
        default_factory=dict,
        description="技能条件分支标记",
    )
    response_attack_success: bool | None = Field(default=None, description="攻击应对是否成功")
    response_defense_success: bool | None = Field(default=None, description="防御应对是否成功")
    response_status_success: bool | None = Field(default=None, description="状态应对是否成功")


class DamageCalculatorCalculateInput(BaseModel):
    """独立伤害计算请求。"""

    attacker: DamageCalculatorParticipantInput = Field(..., description="攻击方")
    defender: DamageCalculatorParticipantInput = Field(..., description="防御方")
    skill_id: str = Field(..., description="技能 ID")
    formula_type: Literal["attack", "status", "starfall"] = Field(
        default="attack",
        description="公式类型；P0/P1 主要支持 attack",
    )
    modifiers: DamageCalculatorModifierInput = Field(
        default_factory=DamageCalculatorModifierInput,
        description="手动修正项",
    )
    observed_damage_value: int | None = Field(
        default=None,
        ge=0,
        description="真实伤害；P1 仅做偏差展示，不写入推算 evidence",
    )
    notes: str | None = Field(default=None, description="备注")


class DamageCalculatorPanelOut(BaseModel):
    """计算得到的面板输出。"""

    hp: int
    physical_attack: int
    physical_defense: int
    magic_attack: int
    magic_defense: int
    speed: int


class DamageCalculatorParticipantOut(BaseModel):
    """参与方输出。"""

    elf_id: str
    elf_name: str | None = None
    element_types: list[str] = Field(default_factory=list)
    nature_id: str | None = None
    nature_name: str | None = None
    panel_stats: DamageCalculatorPanelOut
    panel_source: str


class DamageCalculatorBattleOptionOut(BaseModel):
    """最近战斗可快捷导入的精灵摘要。"""

    side: str
    elf_id: str
    elf_name: str
    avatar: str | None = None
    is_active_elf: bool = False
    current_hp_percent: float | None = None
    nature_id: str | None = None
    nature_name: str | None = None
    individual_talent_distribution: dict[str, Any] | None = None
    panel_stats: DamageCalculatorPanelOut | None = None
    panel_source: str | None = None
    skill_ids: list[str] = Field(default_factory=list)


class DamageCalculatorLatestBattleOut(BaseModel):
    """最近战斗摘要。"""

    battle_id: str
    battle_name: str | None = None
    phase: str
    turn_number: int
    self_active_elf_id: str | None = None
    enemy_active_elf_id: str | None = None
    self_lineup: list[DamageCalculatorBattleOptionOut] = Field(default_factory=list)
    enemy_lineup: list[DamageCalculatorBattleOptionOut] = Field(default_factory=list)


class DamageCalculatorTypeEffectivenessOut(BaseModel):
    """独立计算器前端预填倍率所需的属性克制规则。"""

    attack_element_type: str
    defense_element_type: str
    multiplier: float


class DamageCalculatorBootstrapOut(BaseModel):
    """独立伤害计算器初始化响应。"""

    latest_battle: DamageCalculatorLatestBattleOut | None = None
    type_effectiveness_rules: list[DamageCalculatorTypeEffectivenessOut] = Field(
        default_factory=list,
        description="属性克制规则，用于前端按当前技能与目标系别预填克制倍率",
    )


class DamageCalculatorObservedComparisonOut(BaseModel):
    """真实伤害与理论伤害的对比。"""

    observed_damage_value: int
    predicted_damage_value: int | None = None
    delta_value: int | None = None
    delta_percent_of_prediction: float | None = None
    inference_status: str = "reserved"
    message: str


class DamageCalculatorResultOut(BaseModel):
    """独立伤害计算结果。"""

    status: str
    formula_type: str
    attacker: DamageCalculatorParticipantOut
    defender: DamageCalculatorParticipantOut
    skill_id: str
    skill_name: str | None = None
    damage_value: int | None = None
    damage_percent: float | None = None
    confidence: float
    missing_parts: list[str] = Field(default_factory=list)
    unknown_factors: list[str] = Field(default_factory=list)
    explanation: dict[str, Any] = Field(default_factory=dict)
    multipliers: dict[str, Any] = Field(default_factory=dict)
    observed_comparison: DamageCalculatorObservedComparisonOut | None = None
    side_effect_policy: str = "read_only_no_battle_mutation"


class DamageCalculatorInferDefenderInput(BaseModel):
    """根据真实伤害反推防御方配置候选的请求。"""

    attacker: DamageCalculatorParticipantInput = Field(..., description="攻击方")
    defender_elf_id: str = Field(..., description="防御方精灵 ID")
    skill_id: str = Field(..., description="技能 ID")
    formula_type: Literal["attack"] = Field(default="attack", description="P2 最小版仅支持攻击伤害")
    modifiers: DamageCalculatorModifierInput = Field(
        default_factory=DamageCalculatorModifierInput,
        description="与正向计算一致的修正项",
    )
    observed_damage_value: int = Field(..., gt=0, description="实战观察到的真实伤害")
    top_n: int = Field(default=20, ge=1, le=100, description="返回候选数量")
    notes: str | None = Field(default=None, description="备注")
    candidate_mode: Literal["focused", "default_templates"] = Field(
        default="focused",
        description=(
            "候选枚举模式：focused 只枚举 HP 和相关防御；"
            "default_templates 使用常见三维资质模板"
        ),
    )


class DamageCalculatorDefenderCandidateOut(BaseModel):
    """防御方配置候选。"""

    rank: int
    template_name: str | None = None
    nature_id: str
    nature_name: str
    individual_talent_distribution: DamageCalculatorTalentInput
    relevant_defense_stat: str
    hp_talent: int
    defense_talent: int
    panel_stats: DamageCalculatorPanelOut
    predicted_damage_value: int | None = None
    predicted_damage_percent: float | None = None
    delta_value: int | None = None
    absolute_delta: int | None = None
    score: float
    matched_within_tolerance: bool = False
    unknown_factors: list[str] = Field(default_factory=list)
    missing_parts: list[str] = Field(default_factory=list)


class DamageCalculatorInferDefenderOut(BaseModel):
    """防御方配置候选反推结果。"""

    status: str
    observed_damage_value: int
    skill_id: str
    skill_name: str | None = None
    searched_candidate_count: int
    returned_candidate_count: int
    candidates: list[DamageCalculatorDefenderCandidateOut] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    side_effect_policy: str = "read_only_no_battle_mutation"


class DamageCalculatorInferDefenderSampleInput(BaseModel):
    """批量反推中的单条真实伤害样本。"""

    attacker: DamageCalculatorParticipantInput = Field(..., description="攻击方")
    skill_id: str = Field(..., description="技能 ID")
    formula_type: Literal["attack"] = Field(default="attack", description="当前仅支持攻击伤害")
    modifiers: DamageCalculatorModifierInput = Field(
        default_factory=DamageCalculatorModifierInput,
        description="本条伤害样本的修正项",
    )
    observed_damage_value: int = Field(..., gt=0, description="本条真实伤害")
    label: str | None = Field(default=None, description="前端显示用标签")
    notes: str | None = Field(default=None, description="备注")


class DamageCalculatorInferDefenderBatchInput(BaseModel):
    """多条真实伤害样本联合反推请求。"""

    defender_elf_id: str = Field(..., description="防御方精灵 ID")
    samples: list[DamageCalculatorInferDefenderSampleInput] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="伤害样本列表；同一个防御方配置会累计所有样本偏差",
    )
    candidate_mode: Literal["focused", "default_templates"] = Field(
        default="focused",
        description="候选枚举模式",
    )
    tolerance: int = Field(default=0, ge=0, le=50, description="认为命中的单条伤害容忍偏差")
    top_n: int = Field(default=20, ge=1, le=100, description="返回候选数量")


class DamageCalculatorInferDefenderSampleResultOut(BaseModel):
    """批量反推中某个候选对单条样本的命中情况。"""

    sample_index: int
    sample_label: str | None = None
    skill_id: str
    skill_name: str | None = None
    observed_damage_value: int
    predicted_damage_value: int | None = None
    delta_value: int | None = None
    absolute_delta: int | None = None
    matched_within_tolerance: bool = False
    unknown_factors: list[str] = Field(default_factory=list)
    missing_parts: list[str] = Field(default_factory=list)


class DamageCalculatorBatchDefenderCandidateOut(BaseModel):
    """多样本累计后的防御方候选。"""

    rank: int
    template_name: str | None = None
    nature_id: str
    nature_name: str
    individual_talent_distribution: DamageCalculatorTalentInput
    relevant_defense_stats: list[str] = Field(default_factory=list)
    hp_talent: int
    physical_defense_talent: int
    magic_defense_talent: int
    panel_stats: DamageCalculatorPanelOut
    total_absolute_delta: int
    average_absolute_delta: float
    matched_sample_count: int
    sample_count: int
    score: float
    sample_results: list[DamageCalculatorInferDefenderSampleResultOut] = Field(
        default_factory=list
    )


class DamageCalculatorInferDefenderBatchOut(BaseModel):
    """多条伤害样本联合反推结果。"""

    status: str
    defender_elf_id: str
    searched_candidate_count: int
    returned_candidate_count: int
    tolerance: int
    candidate_mode: str
    candidates: list[DamageCalculatorBatchDefenderCandidateOut] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    side_effect_policy: str = "read_only_no_battle_mutation"
