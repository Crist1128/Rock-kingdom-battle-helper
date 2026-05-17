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
    element_type: str
    skill_category: str
    base_power: int | None = None
    base_energy_cost: int
    priority_modifier: int
    damage_rule_json: str | None = None
    hit_rule_json: str | None = None
    effect_operations_json: str | None = None


class EffectDefinitionOut(ORMBase):
    """
    状态效果定义输出 Schema。

    用于 API 响应中返回状态效果的基础信息。

    Attributes:
        effect_id: 状态唯一标识
        effect_name: 状态显示名称
        category: 状态分类
        polarity: 极性（正面/负面/中性）
        display_group: 显示分组
        owner_scope: 归属范围
        clear_on_switch: 切换精灵时是否清除
        formula_hooks_json: 参与的公式钩子（JSON 字符串）
    """
    effect_id: str
    effect_name: str
    category: str
    polarity: str
    display_group: str
    owner_scope: str
    clear_on_switch: bool
    formula_hooks_json: str | None = None


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
