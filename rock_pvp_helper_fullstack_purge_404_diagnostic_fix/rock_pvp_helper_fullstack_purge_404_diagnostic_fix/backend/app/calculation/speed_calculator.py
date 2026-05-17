"""
速度计算占位器。

第一阶段只允许做最基础的面板速度比较；任何状态、技能先手、行动规则修正都
需要等待规则确认后再接入。这样可以保留速度判断入口，同时避免过早实现复杂规则。
"""


def compare_panel_speed(self_speed: int, enemy_speed: int) -> str:
    """
    比较双方未受状态影响的面板速度。

    Returns:
        str: self_first、enemy_first 或 speed_tie。
    """
    if self_speed > enemy_speed:
        return "self_first"
    if self_speed < enemy_speed:
        return "enemy_first"
    return "speed_tie"
