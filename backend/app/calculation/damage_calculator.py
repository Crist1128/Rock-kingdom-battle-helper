"""伤害计算入口。"""

from app.calculation.attack_damage import AttackDamageCalculator
from app.calculation.formula_context import CalculationPlaceholderResult, DamageFormulaContext


class DamageCalculator:
    """根据公式类型分发到具体伤害计算器。"""

    MISSING_PARTS = [
        "normal_damage_formula_context",
        "rule_resolver",
        "modifier_resolver",
        "special_formula_handlers",
    ]

    def __init__(self) -> None:
        self.attack_damage_calculator = AttackDamageCalculator()

    def calculate(self, context: DamageFormulaContext) -> CalculationPlaceholderResult:
        """计算伤害；上下文不足时返回 formula_unavailable。"""
        if context.formula_type == "attack":
            return self.attack_damage_calculator.calculate(context)
        return CalculationPlaceholderResult(
            status="formula_unavailable",
            formula_type=context.formula_type,
            missing_parts=self.MISSING_PARTS.copy(),
            context_id=context.damage_event_id,
            message=f"暂不支持公式类型：{context.formula_type}",
        )
