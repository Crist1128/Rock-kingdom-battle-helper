"""敌方配置反推引擎。

Milestone 1 的重点是先跑通“玩家观测 -> 候选软评分 -> 候选分布”的闭环。
因此本模块现在提供两个入口：

1. ``process_damage_event``：保留旧的伤害事件入口，当前仍返回公式占位结果；
2. ``process_observation_event``：新的通用观测入口，支持技能出现和速度先后手匹配。

注意：第一阶段默认不硬排除候选。即便某个 matcher 能判断不匹配，也只更新
``match_score`` 和证据链，除非调用方显式允许 ``allow_hard_exclude``。
"""

from __future__ import annotations

from math import exp
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext
from app.inference.match_result import ObservationMatchResult
from app.inference.observation_matcher import ObservationEventInput, ObservationMatcher
from app.models.candidate import BuildCandidate
from app.models.event import DamageEvent
from app.utils.json import dumps_json, loads_json


class InferenceEngine:
    """敌方配置反推引擎。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.damage_calculator = DamageCalculator()
        self.observation_matcher = ObservationMatcher(db)

    def process_damage_event(
        self,
        damage_event: DamageEvent,
        context: DamageFormulaContext,
    ) -> dict:
        """处理旧版伤害事件入口。

        真实伤害公式尚未接入时，该方法继续保持兼容行为：只调用占位计算器，不更新候选。
        后续 Milestone 2 可以把 DamageEvent 转成 ObservationEventInput，再复用
        ``process_observation_event`` 的候选软评分逻辑。
        """
        result = self.damage_calculator.calculate(context)
        damage_event.calculation_confidence = result.confidence
        return {
            "status": result.status,
            "damage_event_id": damage_event.event_id,
            "candidate_filter_applied": False,
            "excluded_candidate_count": 0,
            "confidence": result.confidence,
            "missing_parts": result.missing_parts,
            "message": result.message,
        }

    def process_observation_event(
        self,
        observation: ObservationEventInput,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        """根据玩家录入的观测事件更新候选软评分。

        Args:
            observation: 通用观测事件。Milestone 1 支持 ``skill_seen`` 和 ``speed_order``。
            commit: 是否在方法结束时提交事务。测试或批处理时可传入 ``False``。

        Returns:
            dict: 本次处理摘要，包括匹配数量、冲突数量、unknown 数量和 Top 候选信息。
        """
        candidates = self._load_active_candidates(observation.battle_id, observation.enemy_elf_id)
        matched_count = 0
        mismatched_count = 0
        unknown_count = 0
        hard_excluded_count = 0

        for candidate in candidates:
            match_result = self.observation_matcher.match_candidate(
                observation=observation,
                candidate=candidate,
            )
            self._apply_match_result(candidate, observation, match_result)

            if match_result.matched is True:
                matched_count += 1
            elif match_result.matched is False:
                mismatched_count += 1
            else:
                unknown_count += 1

            # MVP 默认不硬排除；只有调用方显式允许，且 matcher 认为可硬排除时才执行。
            if observation.allow_hard_exclude and match_result.can_hard_exclude:
                candidate.is_excluded = True
                candidate.excluded_reason = match_result.reason
                hard_excluded_count += 1

        self._refresh_confidence(observation.battle_id, observation.enemy_elf_id)
        if commit:
            self.db.commit()

        top_candidate = self._load_top_candidate(observation.battle_id, observation.enemy_elf_id)
        return {
            "status": "processed",
            "battle_id": observation.battle_id,
            "enemy_elf_id": observation.enemy_elf_id,
            "event_id": observation.event_id,
            "observation_type": observation.observation_type.value,
            "candidate_count": len(candidates),
            "matched_count": matched_count,
            "mismatched_count": mismatched_count,
            "unknown_count": unknown_count,
            "hard_excluded_count": hard_excluded_count,
            "hard_filter_applied": observation.allow_hard_exclude,
            "top_candidate_id": top_candidate.candidate_id if top_candidate else None,
            "top_confidence": top_candidate.confidence if top_candidate else None,
        }

    def _load_active_candidates(self, battle_id: str, elf_id: str) -> list[BuildCandidate]:
        """读取当前仍参与推断的候选。"""
        stmt = (
            select(BuildCandidate)
            .where(
                BuildCandidate.battle_id == battle_id,
                BuildCandidate.elf_id == elf_id,
                BuildCandidate.is_excluded.is_(False),
            )
            .order_by(BuildCandidate.candidate_id)
        )
        return list(self.db.scalars(stmt).all())

    def _load_top_candidate(self, battle_id: str, elf_id: str) -> BuildCandidate | None:
        """读取当前置信度最高的候选，用于处理结果摘要。"""
        stmt = (
            select(BuildCandidate)
            .where(
                BuildCandidate.battle_id == battle_id,
                BuildCandidate.elf_id == elf_id,
                BuildCandidate.is_excluded.is_(False),
            )
            .order_by(BuildCandidate.confidence.desc(), BuildCandidate.match_score.desc())
            .limit(1)
        )
        return self.db.scalars(stmt).first()

    def _apply_match_result(
        self,
        candidate: BuildCandidate,
        observation: ObservationEventInput,
        match_result: ObservationMatchResult,
    ) -> None:
        """把 matcher 结果写回候选评分和证据字段。"""
        candidate.match_score = float(candidate.match_score or 0.0) + match_result.score_delta

        if match_result.matched is True:
            candidate.matched_event_ids_json = self._append_json_list(
                candidate.matched_event_ids_json,
                observation.event_id,
            )
        elif match_result.matched is False:
            candidate.mismatched_event_ids_json = self._append_json_list(
                candidate.mismatched_event_ids_json,
                observation.event_id,
            )

        evidence = {
            "event_id": observation.event_id,
            "observation_type": observation.observation_type.value,
            "matched": match_result.matched,
            "reason": match_result.reason,
            "score_delta": match_result.score_delta,
            "unknown_factors": match_result.unknown_factors,
            "observed_value": match_result.observed_value,
            "predicted_value": match_result.predicted_value,
            "predicted_range": match_result.predicted_range,
            "details": match_result.evidence,
        }
        candidate.evidence_ids_json = self._append_json_list(candidate.evidence_ids_json, evidence)

    def _refresh_confidence(self, battle_id: str, elf_id: str, temperature: float = 1.0) -> None:
        """按当前候选池的 match_score 重新计算 softmax 置信度。

        置信度在 Milestone 1 中只用于排序展示，不代表严格概率。使用 softmax 可以让分数
        变化自然反映到 Top-K 分布上，同时保留后续替换为更严谨概率模型的空间。
        """
        candidates = self._load_active_candidates(battle_id, elf_id)
        if not candidates:
            return

        safe_temperature = max(float(temperature), 1e-6)
        max_score = max(float(candidate.match_score or 0.0) for candidate in candidates)
        weights = [
            exp((float(candidate.match_score or 0.0) - max_score) / safe_temperature)
            for candidate in candidates
        ]
        total_weight = sum(weights)
        if total_weight <= 0:
            even_confidence = 1.0 / len(candidates)
            for candidate in candidates:
                candidate.confidence = even_confidence
            return

        for candidate, weight in zip(candidates, weights, strict=True):
            candidate.confidence = weight / total_weight

    @staticmethod
    def _append_json_list(raw_json: str | None, item: Any) -> str:
        """向候选 JSON 列表字段追加内容，并保持已有数据兼容。"""
        data = loads_json(raw_json, [])
        if not isinstance(data, list):
            data = []
        data.append(item)
        return dumps_json(data)
