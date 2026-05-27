"""观测事件类型定义。

Milestone 1 的目标不是一次性实现完整战斗模拟，而是先把“玩家手动录入的事实”
统一抽象为可匹配的观测事件。后续伤害、状态、技能、速度等匹配器都基于这些类型分发。
"""

from enum import StrEnum


class ObservationType(StrEnum):
    """候选反推可以消费的观测事件类型。"""

    DAMAGE_VALUE = "damage_value"
    HP_PERCENT_DELTA = "hp_percent_delta"
    SPEED_ORDER = "speed_order"
    SKILL_SEEN = "skill_seen"
    STATE_TRIGGER = "state_trigger"
    SURVIVAL = "survival"
