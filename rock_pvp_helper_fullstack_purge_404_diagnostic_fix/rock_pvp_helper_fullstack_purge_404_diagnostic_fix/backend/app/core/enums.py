"""
应用枚举定义模块。

本模块定义了系统中使用的所有枚举类型，用于统一状态、类型、阶段等的表示。
使用 Python 3.11+ 的 StrEnum 确保枚举值与字符串兼容，便于序列化和数据库存储。
"""

from enum import StrEnum


class Side(StrEnum):
    """
    战斗方枚举。

    表示战斗中的两个阵营：己方和敌方。

    Attributes:
        SELF: 己方（玩家控制的阵营）
        ENEMY: 敌方（对手阵营）
    """
    SELF = "self"
    ENEMY = "enemy"


class BattlePhase(StrEnum):
    """
    战斗阶段枚举。

    表示一场战斗从创建到归档的完整生命周期。

    Attributes:
        PREPARATION: 准备阶段，可调整阵容和配置
        BATTLE: 战斗阶段，正在进行中
        FINISHED: 已结束，但尚未归档
        ARCHIVED: 已归档，作为历史记录保存
    """
    PREPARATION = "preparation"
    BATTLE = "battle"
    FINISHED = "finished"
    ARCHIVED = "archived"


class StatKey(StrEnum):
    """
    属性维度枚举。

    表示精灵的六维属性，用于属性计算、性格修正等场景。

    Attributes:
        HP: 生命
        PHYSICAL_ATTACK: 物攻（物理攻击）
        PHYSICAL_DEFENSE: 物防（物理防御）
        MAGIC_ATTACK: 魔攻（魔法攻击）
        MAGIC_DEFENSE: 魔防（魔法防御）
        SPEED: 速度
    """
    HP = "hp"
    PHYSICAL_ATTACK = "physical_attack"
    PHYSICAL_DEFENSE = "physical_defense"
    MAGIC_ATTACK = "magic_attack"
    MAGIC_DEFENSE = "magic_defense"
    SPEED = "speed"


class SkillCategory(StrEnum):
    """
    技能类别枚举。

    表示技能的分类，影响技能的伤害计算和效果触发。

    Attributes:
        PHYSICAL: 物理技能，基于物攻和物防计算伤害
        MAGIC: 魔法技能，基于魔攻和魔防计算伤害
        STATUS: 状态技能，用于施加状态或改变战场环境
        SPECIAL: 特殊技能，可能有特殊的伤害计算规则
    """
    PHYSICAL = "physical"
    MAGIC = "magic"
    STATUS = "status"
    SPECIAL = "special"


class EffectCategory(StrEnum):
    """
    状态效果分类枚举。

    统一状态系统中的效果分类，所有状态（包括印记、天气、异常）都使用此分类。

    Attributes:
        STAT_MODIFIER: 普通属性修正（如攻击+1、防御-1）
        ABNORMAL: 异常状态（如中毒、灼烧、冰冻）
        SPECIAL_STATUS: 特殊状态（如萌化）
        MARK: 印记效果
        WEATHER: 天气/战场效果
        DAMAGE_MODIFIER: 伤害修正（如增伤、减伤）
        SKILL_MODIFIER: 技能修正（如威力变化、能耗变化）
        COMBO_MODIFIER: 连击修正
        ACTION_RULE: 行动规则修正（如先手、迅捷、蓄力）
        RESOURCE_RULE: 资源规则修正（如 PP 回复、能量获取）
        SPECIAL_RULE: 特殊规则（如奉献）
    """
    STAT_MODIFIER = "stat_modifier"
    ABNORMAL = "abnormal"
    SPECIAL_STATUS = "special_status"
    MARK = "mark"
    WEATHER = "weather"
    DAMAGE_MODIFIER = "damage_modifier"
    SKILL_MODIFIER = "skill_modifier"
    COMBO_MODIFIER = "combo_modifier"
    ACTION_RULE = "action_rule"
    RESOURCE_RULE = "resource_rule"
    SPECIAL_RULE = "special_rule"


class OwnerScope(StrEnum):
    """
    状态归属范围枚举。

    表示状态效果的归属对象，决定状态跟随的目标。

    Attributes:
        ELF: 归属特定精灵，跟随精灵切换
        SIDE: 归属队伍侧，不随精灵切换清除
        FIELD: 归属战场，影响全场精灵
        SKILL_SLOT: 归属技能槽，影响特定技能
        TURN: 归属回合，仅当前回合有效
    """
    ELF = "elf"
    SIDE = "side"
    FIELD = "field"
    SKILL_SLOT = "skill_slot"
    TURN = "turn"


class DamageDisplayType(StrEnum):
    """
    伤害显示类型枚举。

    区分不同类型的伤害显示方式，用于正确处理伤害数据。

    Attributes:
        SINGLE_DAMAGE: 单次伤害，直接记录伤害值
        VISUAL_TOTAL_DAMAGE: 动画多段但最终显示总伤害，按一次伤害处理
        COMBO_REPEATED_DAMAGE: 连击伤害，每段相同且无总伤害显示
        SPECIAL_DAMAGE: 特殊结算伤害，由特殊规则处理
    """
    SINGLE_DAMAGE = "single_damage"
    VISUAL_TOTAL_DAMAGE = "visual_total_damage"
    COMBO_REPEATED_DAMAGE = "combo_repeated_damage"
    SPECIAL_DAMAGE = "special_damage"


class RuntimeRecordStrategy(StrEnum):
    """
    运行时记录策略枚举。

    定义伤害记录的策略方式。

    Attributes:
        SINGLE_VALUE: 单值记录
        FINAL_TOTAL_ONLY: 仅记录最终总伤害
        PER_HIT_VALUE_AND_COUNT: 记录每段伤害和次数
    """
    SINGLE_VALUE = "single_value"
    FINAL_TOTAL_ONLY = "final_total_only"
    PER_HIT_VALUE_AND_COUNT = "per_hit_value_and_count"


class EventSource(StrEnum):
    """
    事件来源枚举。

    表示战斗事件的来源，用于判断事件可信度。

    优先级：手动输入 > 自动识别 > 系统推算 > 数据库规则

    Attributes:
        DATABASE_RULE: 数据库规则，可信度最低
        MANUAL_INPUT: 手动输入，可信度最高
        AUTO_RECOGNITION: 自动识别（图像识别/OCR）
        SYSTEM_CALCULATED: 系统计算
        SYSTEM_INFERRED: 系统推算
    """
    DATABASE_RULE = "database_rule"
    MANUAL_INPUT = "manual_input"
    AUTO_RECOGNITION = "auto_recognition"
    SYSTEM_CALCULATED = "system_calculated"
    SYSTEM_INFERRED = "system_inferred"


class BattleEventType(StrEnum):
    """
    战斗事件类型枚举。

    定义所有可能的战斗事件类型，用于事件日志记录和回放。

    Attributes:
        SKILL_USE: 技能使用
        DAMAGE: 造成伤害
        COMBO_DAMAGE: 连击伤害
        HEAL: 治疗/回复生命
        ENERGY_CHANGE: 能量变化
        EFFECT_APPLY: 状态施加
        EFFECT_REMOVE: 状态移除
        EFFECT_STACK: 状态叠层
        EFFECT_CONVERT: 状态转换
        EFFECT_TRANSFER: 状态转移
        EFFECT_DISPEL: 状态驱散
        SWITCH_ELF: 精灵切换
        SWITCH_CLEAR: 切换清除状态
        WEATHER_CHANGE: 天气变化
        MARK_CHANGE: 印记变化
    """
    SKILL_USE = "skill_use"
    DAMAGE = "damage"
    COMBO_DAMAGE = "combo_damage"
    HEAL = "heal"
    ENERGY_CHANGE = "energy_change"
    EFFECT_APPLY = "effect_apply"
    EFFECT_REMOVE = "effect_remove"
    EFFECT_STACK = "effect_stack"
    EFFECT_CONVERT = "effect_convert"
    EFFECT_TRANSFER = "effect_transfer"
    EFFECT_DISPEL = "effect_dispel"
    SWITCH_ELF = "switch_elf"
    SWITCH_CLEAR = "switch_clear"
    WEATHER_CHANGE = "weather_change"
    MARK_CHANGE = "mark_change"
