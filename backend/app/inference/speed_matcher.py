"""速度先后手观测匹配器。

Milestone 1 只处理最基础的面板速度比较。若存在技能优先级、先制效果、速度状态修正、
同速随机等未知因素，应把事件降级为 unknown，避免误伤候选。
"""

from app.calculation.speed_calculator import compare_panel_speed
from app.inference.match_result import ObservationMatchResult

_VALID_ORDERS = {"self_first", "enemy_first", "speed_tie"}


class SpeedMatcher:
    """根据候选速度判断玩家录入的先后手观测是否合理。"""

    def match_speed_order(
        self,
        *,
        observed_order: str | None,
        self_speed: int | None,
        candidate_speed: int | None,
        unknown_factors: list[str] | None = None,
        event_weight: float = 1.0,
    ) -> ObservationMatchResult:
        """匹配基础面板速度先后手。

        Args:
            observed_order: 玩家观测到的先后手，取值 self_first/enemy_first/speed_tie。
            self_speed: 己方面板速度。
            candidate_speed: 当前候选敌方面板速度。
            unknown_factors: 可能影响先后手的未知因素。
            event_weight: 本事件基础权重。
        """
        unknown_factors = unknown_factors or []
        if unknown_factors:
            return ObservationMatchResult.unknown_result(
                reason="speed_order_has_unknown_factors",
                unknown_factors=unknown_factors,
                observed_value=observed_order,
                predicted_value=candidate_speed,
            )

        if observed_order not in _VALID_ORDERS:
            return ObservationMatchResult.unknown_result(
                reason="invalid_or_missing_observed_order",
                unknown_factors=["observed_order_missing_or_invalid"],
                observed_value=observed_order,
            )

        if self_speed is None or candidate_speed is None:
            return ObservationMatchResult.unknown_result(
                reason="speed_value_missing",
                unknown_factors=[
                    "self_speed_missing" if self_speed is None else "candidate_speed_missing"
                ],
                observed_value=observed_order,
                predicted_value=candidate_speed,
            )

        predicted_order = compare_panel_speed(self_speed, candidate_speed)
        evidence = {"self_speed": self_speed, "candidate_speed": candidate_speed}
        if predicted_order == observed_order:
            return ObservationMatchResult.matched_result(
                reason="speed_order_matched",
                score_delta=event_weight,
                observed_value=observed_order,
                predicted_value=predicted_order,
                evidence=evidence,
            )

        return ObservationMatchResult.mismatched_result(
            reason="speed_order_mismatched",
            score_delta=-event_weight,
            observed_value=observed_order,
            predicted_value=predicted_order,
            can_hard_exclude=True,
            evidence=evidence,
        )
