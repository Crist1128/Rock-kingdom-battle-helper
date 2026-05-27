"""伤害观测匹配器。

DamageMatcher 不负责计算伤害，只负责把玩家观测值与 DamageCalculator 的结果进行比较。
若公式不可用或存在关键未知因素，则返回 unknown，避免误扣分或误排除。
"""

from app.calculation.formula_context import CalculationPlaceholderResult
from app.inference.match_result import ObservationMatchResult


class DamageMatcher:
    """匹配整数伤害和扣血百分比观测。"""

    def match_damage_value(
        self,
        *,
        observed: int | None,
        result: CalculationPlaceholderResult,
        tolerance: int = 0,
        event_weight: float = 1.5,
    ) -> ObservationMatchResult:
        """比较玩家录入的整数伤害。"""
        if observed is None:
            return ObservationMatchResult.unknown_result(
                reason="observed_damage_missing",
                unknown_factors=["observed_damage_missing"],
            )
        if result.status != "calculated":
            return ObservationMatchResult.unknown_result(
                reason="damage_formula_unavailable",
                unknown_factors=result.missing_parts or ["damage_formula_unavailable"],
                observed_value=observed,
                evidence=result.explanation,
            )
        if result.unknown_factors:
            return ObservationMatchResult.unknown_result(
                reason="damage_result_has_unknown_factors",
                unknown_factors=result.unknown_factors,
                observed_value=observed,
                predicted_value=result.damage_value,
                predicted_range=result.damage_range,
                evidence=result.explanation,
            )

        if result.damage_range is not None:
            lower, upper = result.damage_range
            matched = lower - tolerance <= observed <= upper + tolerance
            predicted_range = result.damage_range
            predicted_value = None
        else:
            if result.damage_value is None:
                return ObservationMatchResult.unknown_result(
                    reason="predicted_damage_missing",
                    unknown_factors=["predicted_damage_missing"],
                    observed_value=observed,
                    evidence=result.explanation,
                )
            matched = abs(observed - result.damage_value) <= tolerance
            predicted_range = None
            predicted_value = result.damage_value

        if matched:
            return ObservationMatchResult.matched_result(
                reason="damage_value_matched",
                score_delta=event_weight,
                observed_value=observed,
                predicted_value=predicted_value,
                evidence={**result.explanation, "predicted_range": predicted_range},
            )
        return ObservationMatchResult.mismatched_result(
            reason="damage_value_mismatched",
            score_delta=-event_weight,
            observed_value=observed,
            predicted_value=predicted_value,
            can_hard_exclude=True,
            evidence={**result.explanation, "predicted_range": predicted_range},
        )

    def match_hp_percent_delta(
        self,
        *,
        observed_pct: float | None,
        result: CalculationPlaceholderResult,
        max_hp: int | None,
        tolerance: float = 1.0,
        event_weight: float = 0.5,
    ) -> ObservationMatchResult:
        """比较玩家录入的扣血百分比。"""
        if observed_pct is None:
            return ObservationMatchResult.unknown_result(
                reason="observed_hp_percent_delta_missing",
                unknown_factors=["observed_hp_percent_delta_missing"],
            )
        if max_hp is None or max_hp <= 0:
            return ObservationMatchResult.unknown_result(
                reason="defender_max_hp_missing",
                unknown_factors=["defender_max_hp_missing"],
                observed_value=observed_pct,
            )
        if result.status != "calculated" or result.damage_value is None:
            return ObservationMatchResult.unknown_result(
                reason="damage_formula_unavailable",
                unknown_factors=result.missing_parts or ["damage_formula_unavailable"],
                observed_value=observed_pct,
                evidence=result.explanation,
            )
        if result.unknown_factors:
            return ObservationMatchResult.unknown_result(
                reason="damage_result_has_unknown_factors",
                unknown_factors=result.unknown_factors,
                observed_value=observed_pct,
                evidence=result.explanation,
            )

        predicted_pct = result.damage_value / max_hp * 100
        matched = abs(observed_pct - predicted_pct) <= tolerance
        if matched:
            return ObservationMatchResult.matched_result(
                reason="hp_percent_delta_matched",
                score_delta=event_weight,
                observed_value=observed_pct,
                predicted_value=predicted_pct,
                evidence={**result.explanation, "max_hp": max_hp, "tolerance": tolerance},
            )
        return ObservationMatchResult.mismatched_result(
            reason="hp_percent_delta_mismatched",
            score_delta=-event_weight,
            observed_value=observed_pct,
            predicted_value=predicted_pct,
            can_hard_exclude=False,
            evidence={**result.explanation, "max_hp": max_hp, "tolerance": tolerance},
        )
