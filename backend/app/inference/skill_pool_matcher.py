"""技能出现观测匹配器。

当玩家确认敌方使用了某个技能时，可以用该事实约束候选的 possible_skill_ids_json。
注意：爬虫技能池可能不完整，所以本匹配器支持 ``skill_pool_reliable=False``，此时不匹配
只会返回 unknown，而不会扣分或硬排除。
"""

from app.inference.match_result import ObservationMatchResult


class SkillPoolMatcher:
    """根据候选技能池判断“技能出现”观测是否合理。"""

    def match_skill_seen(
        self,
        *,
        skill_id: str | None,
        possible_skill_ids: list[str] | None,
        skill_pool_reliable: bool = True,
        event_weight: float = 2.0,
    ) -> ObservationMatchResult:
        """匹配玩家观测到的敌方技能。

        Args:
            skill_id: 玩家确认出现的技能 ID。
            possible_skill_ids: 当前候选可学习或可能携带的技能 ID 列表。
            skill_pool_reliable: 技能池数据是否足够可靠。数据不可靠时不做负向判断。
            event_weight: 本事件基础权重。
        """
        if not skill_id:
            return ObservationMatchResult.unknown_result(
                reason="missing_skill_id",
                unknown_factors=["skill_id_missing"],
            )

        if possible_skill_ids is None:
            return ObservationMatchResult.unknown_result(
                reason="candidate_skill_pool_missing",
                unknown_factors=["candidate_skill_pool_missing"],
                observed_value=skill_id,
            )

        if skill_id in possible_skill_ids:
            return ObservationMatchResult.matched_result(
                reason="skill_exists_in_candidate_pool",
                score_delta=event_weight,
                observed_value=skill_id,
                predicted_value=skill_id,
                evidence={"possible_skill_count": len(possible_skill_ids)},
            )

        if not skill_pool_reliable:
            return ObservationMatchResult.unknown_result(
                reason="skill_not_found_but_pool_unreliable",
                unknown_factors=["skill_pool_unreliable"],
                observed_value=skill_id,
                evidence={"possible_skill_count": len(possible_skill_ids)},
            )

        return ObservationMatchResult.mismatched_result(
            reason="skill_not_in_candidate_pool",
            score_delta=-event_weight,
            observed_value=skill_id,
            can_hard_exclude=True,
            evidence={"possible_skill_count": len(possible_skill_ids)},
        )
