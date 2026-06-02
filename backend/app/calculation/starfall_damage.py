"""星陨印记伤害计算。"""

from decimal import Decimal
from typing import Any

from app.calculation.formula_context import CalculationPlaceholderResult, DamageFormulaContext
from app.calculation.rounding import floor_damage


class StarfallDamageCalculator:
    """计算星陨印记触发伤害。"""

    SUPPORTED_CATEGORIES = {"physical", "magic"}
    ILLUSION_TYPES = {"幻", "幻系", "illusion"}

    def calculate(self, context: DamageFormulaContext) -> CalculationPlaceholderResult:
        """计算星陨伤害。"""
        missing_parts = self._validate_context(context)
        if missing_parts:
            return CalculationPlaceholderResult(
                status="formula_unavailable",
                formula_type="starfall",
                context_id=context.damage_event_id,
                missing_parts=missing_parts,
                unknown_factors=context.unknown_factors.copy(),
                message="星陨伤害上下文不完整，无法计算。",
            )

        trigger_element = context.trigger_skill_element_type
        if trigger_element in self.ILLUSION_TYPES:
            return CalculationPlaceholderResult(
                status="not_triggered",
                formula_type="starfall",
                context_id=context.damage_event_id,
                message="幻系攻击技能不会触发星陨印记。",
                explanation={
                    "trigger_skill_element_type": trigger_element,
                    "trigger_condition": "non_illusion_attack_skill",
                },
            )

        unknown_factors = context.unknown_factors.copy()
        if trigger_element is None:
            unknown_factors.append("trigger_skill_element_type_missing")

        offense, defense = self._select_offense_defense(context)
        layers = max(int(context.effect_layers or 1), 1)
        starfall_power = self.calculate_starfall_power(layers)
        type_multiplier = self._to_decimal(context.type_multiplier)
        reductions = [self._to_decimal(item) for item in context.damage_reductions]
        reduction_product = self._product(Decimal("1") - item for item in reductions)

        raw_damage = (
            (offense / defense)
            * Decimal(37)
            / Decimal(41)
            * Decimal(starfall_power)
            * type_multiplier
            * reduction_product
        )
        damage = floor_damage(raw_damage)

        return CalculationPlaceholderResult(
            status="calculated",
            formula_type="starfall",
            damage_value=damage,
            confidence=1.0 if not unknown_factors else 0.5,
            context_id=context.damage_event_id,
            unknown_factors=unknown_factors,
            message="星陨伤害计算完成。",
            explanation={
                "effect_id": context.effect_id,
                "layers": layers,
                "starfall_power": starfall_power,
                "starfall_element_type": context.starfall_element_type,
                "trigger_skill_id": context.trigger_skill_id,
                "trigger_skill_category": self._trigger_category(context),
                "trigger_skill_element_type": trigger_element,
                "offense_stat": str(offense),
                "defense_stat": str(defense),
                "uses_type_effectiveness": True,
                "type_multiplier": str(type_multiplier),
                "affected_by_stab": False,
                "affected_by_weather": False,
                "affected_by_display_power": False,
                "affected_by_unstable_multiplier": False,
                "damage_reductions": [str(item) for item in reductions],
                "reduction_product": str(reduction_product),
                "raw_damage": str(raw_damage),
                "rounding": "floor_final",
                "final_damage": damage,
                "after_settlement": {"layer_change": "clear"},
            },
        )

    @staticmethod
    def calculate_starfall_power(layers: int) -> int:
        """星陨威力：layers^2 + layers * 24 - 24。"""
        return layers * layers + layers * 24 - 24

    def _validate_context(self, context: DamageFormulaContext) -> list[str]:
        missing: list[str] = []
        if context.attacker_panel_stats is None:
            missing.append("attacker_panel_stats")
        if context.defender_panel_stats is None:
            missing.append("defender_panel_stats")
        if self._trigger_category(context) not in self.SUPPORTED_CATEGORIES:
            missing.append("trigger_skill_category")
        if context.effect_layers is None:
            missing.append("effect_layers")
        return missing

    def _select_offense_defense(self, context: DamageFormulaContext) -> tuple[Decimal, Decimal]:
        assert context.attacker_panel_stats is not None
        assert context.defender_panel_stats is not None
        if self._trigger_category(context) == "physical":
            return (
                Decimal(context.attacker_panel_stats.physical_attack),
                Decimal(context.defender_panel_stats.physical_defense),
            )
        return (
            Decimal(context.attacker_panel_stats.magic_attack),
            Decimal(context.defender_panel_stats.magic_defense),
        )

    @staticmethod
    def _trigger_category(context: DamageFormulaContext) -> str | None:
        return context.trigger_skill_category or context.skill_category

    @staticmethod
    def _to_decimal(value: Decimal | int | float | str | None) -> Decimal:
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
