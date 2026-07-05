"""
静态规则 Schema 定义模块。

本模块定义静态规则相关的 Pydantic Schema，用于：
- 精灵定义的数据校验和序列化
- 性格定义的数据校验和序列化
- 技能定义的数据校验和序列化
- 状态效果定义的数据校验和序列化
- 属性数据块的定义

所有输出 Schema 都继承 ORMBase，支持直接从 ORM 模型转换。
"""

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class ElfDefinitionOut(ORMBase):
    """
    精灵定义输出 Schema。

    用于 API 响应中返回精灵的基础信息。
    不包含所有字段，只包含常用信息。

    Attributes:
        elf_id: 精灵唯一标识
        elf_name: 精灵显示名称
        avatar: 精灵头像路径
        element_types_json: 系别类型（JSON 字符串）
        base_hp_talent: 生命种族资质
        base_physical_attack_talent: 物攻种族资质
        base_physical_defense_talent: 物防种族资质
        base_magic_attack_talent: 魔攻种族资质
        base_magic_defense_talent: 魔防种族资质
        base_speed_talent: 速度种族资质
        data_version: 数据版本
    """
    elf_id: str
    elf_name: str
    avatar: str
    element_types_json: str
    base_hp_talent: int
    base_physical_attack_talent: int
    base_physical_defense_talent: int
    base_magic_attack_talent: int
    base_magic_defense_talent: int
    base_speed_talent: int
    data_version: str | None = None


class NatureDefinitionOut(ORMBase):
    """
    性格定义输出 Schema。

    用于 API 响应中返回性格的修正规则。

    Attributes:
        nature_id: 性格唯一标识
        nature_name: 性格显示名称
        positive_stat: 正面修正属性
        positive_multiplier: 正面修正倍率
        negative_stat: 负面修正属性
        negative_multiplier: 负面修正倍率
        neutral_multiplier: 中性修正倍率
    """
    nature_id: str
    nature_name: str
    positive_stat: str
    positive_multiplier: float
    negative_stat: str
    negative_multiplier: float
    neutral_multiplier: float


class SkillDefinitionOut(ORMBase):
    """
    技能定义输出 Schema。

    用于 API 响应中返回技能的基础信息。

    Attributes:
        skill_id: 技能唯一标识
        skill_name: 技能显示名称
        raw_description: 技能图鉴原始中文效果描述
        element_type: 技能系别类型
        skill_category: 技能类别
        base_power: 基础威力（None 表示无威力值）
        base_energy_cost: 基础能量消耗
        priority_modifier: 先手优先级修正
        damage_rule_json: 伤害规则（JSON 字符串）
        hit_rule_json: 连击规则（JSON 字符串）
        effect_operations_json: 效果操作（JSON 字符串）
    """
    skill_id: str
    skill_name: str
    raw_description: str | None = None
    element_type: str
    skill_category: str
    base_power: int | None = None
    base_energy_cost: int
    priority_modifier: int
    damage_rule_json: str | None = None
    hit_rule_json: str | None = None
    effect_operations_json: str | None = None


class SkillRuleReviewOut(SkillDefinitionOut):
    """技能规则审阅列表输出。"""

    review_status: str = Field(..., description="人工审阅状态")
    review_notes: str | None = Field(default=None, description="人工审阅备注")
    has_damage_rule: bool = Field(..., description="是否已有伤害/防御规则 JSON")
    has_hit_rule: bool = Field(..., description="是否已有命中/连击规则 JSON")
    has_effect_operations: bool = Field(..., description="是否已有结构化效果操作")
    rule_source: str = Field(..., description="规则来源摘要")


class SkillRuleCapabilityItem(BaseModel):
    """技能机制能力审计条目。"""

    key: str = Field(..., description="机制或规则键")
    label: str = Field(..., description="中文说明")
    implemented: bool = Field(..., description="当前代码是否有执行链")
    tested: bool = Field(default=False, description="是否已有自动化测试覆盖")
    count: int = Field(default=0, description="规则库中出现次数")
    examples: list[str] = Field(default_factory=list, description="示例技能或规则")
    notes: str | None = Field(default=None, description="风险或剩余说明")


class SkillRuleCapabilityAuditOut(BaseModel):
    """技能规则执行能力审计输出。"""

    total_skills: int = Field(..., description="技能总数")
    review_status_counts: dict[str, int] = Field(
        default_factory=dict,
        description="审阅状态统计",
    )
    executable_operation_counts: dict[str, int] = Field(
        default_factory=dict,
        description="已支持 effect operation 类型统计",
    )
    unsupported_operation_counts: dict[str, int] = Field(
        default_factory=dict,
        description="尚未支持 effect operation 类型统计",
    )
    future_hook_counts: dict[str, int] = Field(
        default_factory=dict,
        description="future_hooks 类型统计",
    )
    supported_future_hook_counts: dict[str, int] = Field(
        default_factory=dict,
        description="已有执行链或最小状态机的 future_hooks 统计",
    )
    reserved_future_hook_counts: dict[str, int] = Field(
        default_factory=dict,
        description="仍保留为接口/未执行的 future_hooks 统计",
    )
    implemented_capabilities: list[SkillRuleCapabilityItem] = Field(
        default_factory=list,
        description="已实现能力清单",
    )
    pending_capabilities: list[SkillRuleCapabilityItem] = Field(
        default_factory=list,
        description="未实现或仅部分实现机制清单",
    )
    risk_notes: list[str] = Field(default_factory=list, description="审计风险提示")


class SkillRuleManualUpdate(BaseModel):
    """手动维护技能规则请求。

    字段未传表示保持原值；显式传 null 表示清空对应 JSON 字段。
    """

    damage_rule: dict[str, Any] | None = Field(
        default=None,
        description="伤害、防御、应对等规则对象；不确定时不要填写伪规则",
    )
    hit_rule: dict[str, Any] | None = Field(default=None, description="命中/连击规则对象")
    effect_operations: list[dict[str, Any]] | None = Field(
        default=None,
        description="技能结构化效果操作数组",
    )
    review_status: str = Field(
        default="structured",
        description="审阅状态：structured/partial/needs_review/ambiguous/unreviewed",
    )
    review_notes: str | None = Field(default=None, description="人工备注或待确认原因")


class EffectDefinitionOut(ORMBase):
    """
    状态效果定义输出 Schema。

    用于 API 响应中返回状态效果定义。阶段 A 起该结构返回完整审阅字段，
    让前端规则库可以直接检查状态挂载范围、叠层、清除规则、公式钩子和资源修正。

    Attributes:
        effect_id: 状态唯一标识
        effect_name: 状态显示名称
        icon: 状态图标
        category: 状态分类
        polarity: 极性（正面/负面/中性）
        display_group: 显示分组
        display_priority: 显示优先级
        owner_scope: 归属范围
        target_scope: 目标范围
        attach_target_type: 实际挂载目标类型
        clear_on_switch: 切换精灵时是否清除
        formula_hooks_json: 参与的公式钩子（JSON 字符串）
    """

    effect_id: str
    effect_name: str
    icon: str | None = None
    category: str
    polarity: str
    display_group: str
    display_priority: int
    owner_scope: str
    target_scope: str
    attach_target_type: str
    is_visible_icon: bool
    is_recognizable_by_icon: bool
    recognition_alias_json: str | None = None
    default_layers: int
    max_layers: int | None = None
    stack_rule: str
    refresh_rule: str | None = None
    duration_type: str
    default_duration_turns: int | None = None
    default_duration_uses: int | None = None
    clear_on_switch: bool
    clear_by_abnormal_cleanse: bool
    clear_by_stat_clear: bool
    clear_by_mark_clear: bool
    clear_by_weather_replace: bool
    clear_by_skill_specific: bool
    can_be_transferred: bool
    can_be_converted: bool
    can_be_inherited: bool
    can_be_stolen: bool
    can_be_doubled: bool
    conflict_group: str | None = None
    conflict_policy: str | None = None
    formula_hooks_json: str | None = None
    stat_modifier_json: str | None = None
    damage_modifier_json: str | None = None
    skill_modifier_json: str | None = None
    action_modifier_json: str | None = None
    resource_modifier_json: str | None = None
    special_rule_id: str | None = None
    developer_notes: str | None = None
    data_version: str | None = None


class StatBlock(BaseModel):
    """
    属性数据块 Schema。

    用于表示精灵的六维属性值，可用于：
    - 面板属性展示
    - 属性计算输入/输出
    - 种族资质、个体资质等

    Attributes:
        hp: 生命
        physical_attack: 物攻（物理攻击）
        physical_defense: 物防（物理防御）
        magic_attack: 魔攻（魔法攻击）
        magic_defense: 魔防（魔法防御）
        speed: 速度
    """
    hp: int = Field(..., description="生命")
    physical_attack: int = Field(..., description="物攻")
    physical_defense: int = Field(..., description="物防")
    magic_attack: int = Field(..., description="魔攻")
    magic_defense: int = Field(..., description="魔防")
    speed: int = Field(..., description="速度")
