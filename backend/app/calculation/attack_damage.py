"""普通攻击伤害计算。

本模块只做“已经解析好的公式输入”的纯数学计算，不负责判断应对是否成功、天气是否生效、
减伤来源是否合法等业务分支。这些分支后续由 RuleResolver / ModifierResolver 提供。
"""

from decimal import Decimal
from typing import Any

from app.calculation.formula_context import CalculationPlaceholderResult, DamageFormulaContext
from app.calculation.rounding import floor_damage


class AttackDamageCalculator:
    """最小可用普通攻击伤害计算器。"""

    SUPPORTED_CATEGORIES = {"physical", "magic"}

    def calculate(self, context: DamageFormulaContext) -> CalculationPlaceholderResult:
        """计算单段或固定段数普通攻击伤害。"""
        missing_parts = self._validate_context(context)
        if missing_parts:
            return CalculationPlaceholderResult(
                status="formula_unavailable",
                formula_type="attack",
                context_id=context.damage_event_id,
                missing_parts=missing_parts,
                unknown_factors=context.unknown_factors.copy(),
                message="普通攻击伤害上下文不完整，无法计算。",
            )

        offense, defense = self._select_offense_defense(context)
        display_power = self._resolve_display_power(context)
        reductions = [self._to_decimal(item) for item in context.damage_reductions]
        reduction_product = self._product(Decimal("1") - item for item in reductions)
        hit_count = max(int(context.hit_count or 1), 1)
        unstable_multiplier = self._to_decimal(context.unstable_multiplier)

        # 按当前数学建模文档：
        # raw = (A/D * 37/41) * (display_power * unstable) * H * reductions
        raw_single = (
            (offense / defense)
            * Decimal(37)
            / Decimal(41)
            * display_power
            * unstable_multiplier
            * reduction_product
        )
        single_damage = floor_damage(raw_single)
        total_damage = single_damage * hit_count

        return CalculationPlaceholderResult(
            status="calculated",
            formula_type="attack",
            damage_value=total_damage,
            confidence=1.0 if not context.unknown_factors else 0.5,
            context_id=context.damage_event_id,
            unknown_factors=context.unknown_factors.copy(),
            message="普通攻击伤害计算完成。",
            explanation={
                "offense_stat": str(offense),
                "defense_stat": str(defense),
                "display_power": str(display_power),
                "unstable_multiplier": str(unstable_multiplier),
                "damage_reductions": [str(item) for item in reductions],
                "reduction_product": str(reduction_product),
                "raw_single_damage": str(raw_single),
                "single_damage": single_damage,
                "hit_count": hit_count,
                "total_damage": total_damage,
                "rule_resolution_enabled": context.rule_resolution_enabled,
                "rule_resolution_details": context.rule_resolution_details,
            },
        )

    def _validate_context(self, context: DamageFormulaContext) -> list[str]:
        """返回缺失字段列表；列表为空表示可计算。"""
        missing: list[str] = []
        if context.formula_type != "attack":
            missing.append("unsupported_formula_type")
        if context.attacker_panel_stats is None:
            missing.append("attacker_panel_stats")
        if context.defender_panel_stats is None:
            missing.append("defender_panel_stats")
        if context.skill_category not in self.SUPPORTED_CATEGORIES:
            missing.append("skill_category")
        if context.display_power is None and context.base_power is None:
            missing.append("base_power_or_display_power")
        return missing

    def _select_offense_defense(self, context: DamageFormulaContext) -> tuple[Decimal, Decimal]:
        """根据技能类别选择物攻/物防或魔攻/魔防。"""
        assert context.attacker_panel_stats is not None
        assert context.defender_panel_stats is not None
        if context.skill_category == "physical":
            return (
                Decimal(context.attacker_panel_stats.physical_attack),
                Decimal(context.defender_panel_stats.physical_defense),
            )
        return (
            Decimal(context.attacker_panel_stats.magic_attack),
            Decimal(context.defender_panel_stats.magic_defense),
        )

    def _resolve_display_power(self, context: DamageFormulaContext) -> Decimal:
        """计算显示威力；若调用方直接给 display_power，则优先使用。"""
        if context.display_power is not None:
            return self._to_decimal(context.display_power)
        base_power = self._to_decimal(context.base_power)
        return (
            (base_power * self._to_decimal(context.response_multiplier)
             + self._to_decimal(context.flat_power_bonus))
            * self._to_decimal(context.power_multiplier)
            * self._to_decimal(context.stat_stage_multiplier)
            * self._to_decimal(context.stab_multiplier)
            * self._to_decimal(context.type_multiplier)
            * self._to_decimal(context.weather_multiplier)
        )

    @staticmethod
    def _to_decimal(value: Decimal | int | float | str | None) -> Decimal:
        """安全转 Decimal，避免 float 二进制误差扩散。"""
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _product(values: Any) -> Decimal:
        result = Decimal("1")
        for value in values:
            result *= value
        return result
