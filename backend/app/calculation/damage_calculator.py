"""
伤害计算占位器。

本文件刻意不实现真实伤害公式。当前阶段的目标是稳定事件流和数据结构，
避免使用错误公式污染候选配置。公式确认后，只需要替换 calculate 方法内部
逻辑，并保持输入输出结构不变。
"""

from app.calculation.formula_context import CalculationPlaceholderResult, DamageFormulaContext


class DamageCalculator:
    """
    伤害计算入口。

    当前实现返回公式不可用占位结果，不进行任何伤害推导，也不排除候选配置。
    后续公式确认后，可在这里接入普通伤害、固定伤害、百分比伤害和特殊公式。
    """

    MISSING_PARTS = [
        "normal_damage_formula",
        "rounding_policy",
        "damage_modifier_order",
        "defense_modifier_position",
        "combo_per_hit_formula",
        "special_formula_handlers",
    ]

    def calculate(self, context: DamageFormulaContext) -> CalculationPlaceholderResult:
        """
        返回公式不可用结果。

        Args:
            context: 伤害公式上下文。

        Returns:
            CalculationPlaceholderResult: 明确标识公式未实现的计算结果。
        """
        return CalculationPlaceholderResult(
            missing_parts=self.MISSING_PARTS.copy(),
            context_id=context.damage_event_id,
        )
