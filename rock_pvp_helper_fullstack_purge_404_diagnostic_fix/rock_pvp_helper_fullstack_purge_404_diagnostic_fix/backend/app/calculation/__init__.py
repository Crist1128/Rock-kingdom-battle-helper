"""
计算模块。

当前只实现已经明确的面板属性计算；伤害、速度修正和特殊公式只提供稳定接口
和占位返回，等待公式确认后再实现真实计算。
"""

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import CalculationPlaceholderResult, DamageFormulaContext
from app.calculation.stat_calculator import (
    BaseTalentBlock,
    IndividualTalentDistribution,
    NatureRule,
    PanelStats,
    StatCalculator,
)

__all__ = [
    "BaseTalentBlock",
    "CalculationPlaceholderResult",
    "DamageCalculator",
    "DamageFormulaContext",
    "IndividualTalentDistribution",
    "NatureRule",
    "PanelStats",
    "StatCalculator",
]
