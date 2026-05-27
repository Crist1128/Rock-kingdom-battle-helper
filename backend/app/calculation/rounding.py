"""公式取整工具。"""

from decimal import ROUND_FLOOR, Decimal


def floor_damage(value: Decimal) -> int:
    """正数伤害最终向下取整。

    目前数学建模文档约定：普通攻击伤害先保留 Decimal 精度，最终统一 floor。
    """
    if value <= 0:
        return 0
    return int(value.to_integral_value(rounding=ROUND_FLOOR))
