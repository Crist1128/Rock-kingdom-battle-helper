"""状态伤害与阈值结算计算。"""

from decimal import Decimal

from app.calculation.formula_context import CalculationPlaceholderResult, DamageFormulaContext
from app.calculation.rounding import floor_damage


class StatusDamageCalculator:
    """计算灼烧、中毒、寄生、冻结和棘刺等状态结算。"""

    BURN_EFFECT_IDS = {"effect_burn", "burn"}
    POISON_EFFECT_IDS = {"effect_poison", "poison", "effect_poison_mark", "poison_mark"}
    LEECH_EFFECT_IDS = {"effect_leech_seed", "leech_seed", "leech"}
    FREEZE_EFFECT_IDS = {"effect_freeze", "freeze"}
    THORN_EFFECT_IDS = {"effect_thorn_mark", "thorn_mark", "thorn"}

    def calculate(self, context: DamageFormulaContext) -> CalculationPlaceholderResult:
        """按 effect_id 分发状态伤害。"""
        effect_id = context.effect_id
        if effect_id is None:
            return self._unavailable(context, ["effect_id"])
        if effect_id in self.BURN_EFFECT_IDS:
            return self._percent_damage(
                context,
                percent_per_layer=Decimal("0.02"),
                element_type="火",
                uses_type_effectiveness=True,
                after_settlement={"layer_change": "halve_floor"},
            )
        if effect_id in self.POISON_EFFECT_IDS:
            return self._percent_damage(
                context,
                percent_per_layer=Decimal("0.03"),
                element_type="毒",
                uses_type_effectiveness=True,
                after_settlement={"layer_change": "unchanged"},
            )
        if effect_id in self.LEECH_EFFECT_IDS:
            return self._percent_damage(
                context,
                percent_per_layer=Decimal("0.06"),
                element_type=None,
                uses_type_effectiveness=False,
                heal_opponent_by_damage=True,
                after_settlement={"layer_change": "unchanged"},
            )
        if effect_id in self.THORN_EFFECT_IDS:
            return self._percent_damage(
                context,
                percent_per_layer=Decimal("0.06"),
                element_type=None,
                uses_type_effectiveness=False,
                after_settlement={"layer_change": "unchanged"},
            )
        if effect_id in self.FREEZE_EFFECT_IDS:
            return self._freeze_threshold(context)
        return self._unavailable(context, [f"unsupported_effect_id:{effect_id}"])

    def _percent_damage(
        self,
        context: DamageFormulaContext,
        *,
        percent_per_layer: Decimal,
        element_type: str | None,
        uses_type_effectiveness: bool,
        after_settlement: dict[str, str],
        heal_opponent_by_damage: bool = False,
    ) -> CalculationPlaceholderResult:
        """计算按最大生命百分比造成的状态伤害。"""
        if context.defender_max_hp is None:
            return self._unavailable(context, ["defender_max_hp"])

        layers = max(int(context.effect_layers or 1), 1)
        type_multiplier = (
            self._to_decimal(context.type_multiplier) if uses_type_effectiveness else Decimal("1")
        )
        raw_damage = Decimal(context.defender_max_hp) * percent_per_layer * layers * type_multiplier
        damage = floor_damage(raw_damage)
        secondary_events: list[dict[str, object]] = []
        if heal_opponent_by_damage:
            secondary_events.append(
                {"type": "heal", "target": "source_or_opponent", "value": damage}
            )

        return CalculationPlaceholderResult(
            status="calculated",
            formula_type="status",
            damage_value=damage,
            confidence=1.0 if not context.unknown_factors else 0.5,
            context_id=context.damage_event_id,
            unknown_factors=context.unknown_factors.copy(),
            message="状态伤害计算完成。",
            secondary_events=secondary_events,
            explanation={
                "effect_id": context.effect_id,
                "max_hp": context.defender_max_hp,
                "layers": layers,
                "percent_per_layer": str(percent_per_layer),
                "element_type": element_type,
                "uses_type_effectiveness": uses_type_effectiveness,
                "type_multiplier": str(type_multiplier),
                "raw_damage": str(raw_damage),
                "rounding": "floor_final",
                "final_damage": damage,
                "after_settlement": after_settlement,
            },
        )

    def _freeze_threshold(self, context: DamageFormulaContext) -> CalculationPlaceholderResult:
        """计算冻结阈值是否触发。"""
        layers = max(int(context.effect_layers or 1), 1)
        threshold_percent = Decimal(layers) * Decimal("5")
        triggered = None
        if context.defender_hp_percent is not None:
            triggered = self._to_decimal(context.defender_hp_percent) <= threshold_percent

        unknown_factors = context.unknown_factors.copy()
        if triggered is None:
            unknown_factors.append("defender_hp_percent_missing")

        return CalculationPlaceholderResult(
            status="calculated" if triggered is not None else "partial",
            formula_type="status",
            damage_value=None,
            confidence=1.0 if triggered is not None and not context.unknown_factors else 0.5,
            context_id=context.damage_event_id,
            unknown_factors=unknown_factors,
            message=(
                "冻结阈值结算完成。"
                if triggered is not None
                else "缺少当前生命百分比，无法判断冻结是否触发。"
            ),
            explanation={
                "effect_id": context.effect_id,
                "layers": layers,
                "threshold_percent": str(threshold_percent),
                "defender_hp_percent": context.defender_hp_percent,
                "trigger_condition": "hp_percent <= layers * 5",
                "defeated_by_freeze": triggered,
            },
        )

    @staticmethod
    def _unavailable(
        context: DamageFormulaContext,
        missing_parts: list[str],
    ) -> CalculationPlaceholderResult:
        return CalculationPlaceholderResult(
            status="formula_unavailable",
            formula_type="status",
            context_id=context.damage_event_id,
            missing_parts=missing_parts,
            unknown_factors=context.unknown_factors.copy(),
            message="状态伤害上下文不完整，无法计算。",
        )

    @staticmethod
    def _to_decimal(value: Decimal | int | float | str | None) -> Decimal:
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
