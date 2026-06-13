"""实时面板估计使用的观察事件类型定义。"""

from enum import StrEnum


class ObservationType(StrEnum):
    """EstimateService 可以消费的观察事件类型。"""

    DAMAGE_VALUE = "damage_value"
    HP_PERCENT_DELTA = "hp_percent_delta"
    SPEED_ORDER = "speed_order"
    SKILL_SEEN = "skill_seen"
    STATE_TRIGGER = "state_trigger"
    SURVIVAL = "survival"
