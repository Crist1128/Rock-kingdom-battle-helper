from enum import StrEnum


class Side(StrEnum):
    SELF = "self"
    ENEMY = "enemy"


class BattlePhase(StrEnum):
    PREPARATION = "preparation"
    BATTLE = "battle"
    FINISHED = "finished"
    ARCHIVED = "archived"


class StatKey(StrEnum):
    HP = "hp"
    PHYSICAL_ATTACK = "physical_attack"
    PHYSICAL_DEFENSE = "physical_defense"
    MAGIC_ATTACK = "magic_attack"
    MAGIC_DEFENSE = "magic_defense"
    SPEED = "speed"


class SkillCategory(StrEnum):
    PHYSICAL = "physical"
    MAGIC = "magic"
    STATUS = "status"
    SPECIAL = "special"


class EffectCategory(StrEnum):
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
    ELF = "elf"
    SIDE = "side"
    FIELD = "field"
    SKILL_SLOT = "skill_slot"
    TURN = "turn"


class DamageDisplayType(StrEnum):
    SINGLE_DAMAGE = "single_damage"
    VISUAL_TOTAL_DAMAGE = "visual_total_damage"
    COMBO_REPEATED_DAMAGE = "combo_repeated_damage"
    SPECIAL_DAMAGE = "special_damage"


class RuntimeRecordStrategy(StrEnum):
    SINGLE_VALUE = "single_value"
    FINAL_TOTAL_ONLY = "final_total_only"
    PER_HIT_VALUE_AND_COUNT = "per_hit_value_and_count"


class EventSource(StrEnum):
    DATABASE_RULE = "database_rule"
    MANUAL_INPUT = "manual_input"
    AUTO_RECOGNITION = "auto_recognition"
    SYSTEM_CALCULATED = "system_calculated"
    SYSTEM_INFERRED = "system_inferred"


class BattleEventType(StrEnum):
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
