"""敌方配置反推引擎。

Milestone 1 的重点是先跑通“玩家观测 -> 候选软评分 -> 候选分布”的闭环。
因此本模块现在提供两个入口：

1. ``process_damage_event``：保留旧的伤害事件入口，当前仍返回公式占位结果；
2. ``process_observation_event``：新的通用观测入口，支持技能出现和速度先后手匹配。

注意：第一阶段默认不硬排除候选。即便某个 matcher 能判断不匹配，也只更新
``match_score`` 和证据链，除非调用方显式允许 ``allow_hard_exclude``。
"""

from __future__ import annotations

from collections import defaultdict
from math import exp
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext, PanelStats
from app.inference.match_result import ObservationMatchResult
from app.inference.observation_matcher import ObservationEventInput, ObservationMatcher
from app.inference.observation_payload import normalize_observation_payload
from app.inference.observation_types import ObservationType
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
        observation = observation.model_copy(
            update={
                "payload": normalize_observation_payload(
                    observation.payload,
                    observation_type=observation.observation_type,
                    observed_value=observation.observed_value,
                )
            }
        )
        candidates = self._load_active_candidates(observation.battle_id, observation.enemy_elf_id)
        optimized_result = self._try_process_grouped_damage_observation(
            observation,
            candidates,
            commit=commit,
        )
        if optimized_result is not None:
            return optimized_result

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

            # MVP 默认不硬排除；只有调用方显式允许、matcher 认为可排除，且当前观测
            # 满足“单纯普通伤害”的保护条件时才执行。
            if self._should_hard_exclude(observation, match_result):
                candidate.is_excluded = True
                candidate.excluded_reason = match_result.reason
                hard_excluded_count += 1

        self._refresh_confidence_for_candidates(candidates)
        if commit:
            self.db.commit()

        top_candidate = self._top_candidate_from_rows(candidates)
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

    def _try_process_grouped_damage_observation(
        self,
        observation: ObservationEventInput,
        candidates: list[BuildCandidate],
        *,
        commit: bool,
    ) -> dict[str, Any] | None:
        """对普通伤害观测使用按候选面板分组的快速路径。

        候选池中大量候选共享相同防御面板。普通伤害公式在敌方作为防御方时只依赖
        候选防御面板、技能规则和固定观测上下文，因此可以先解析一次规则，再按面板
        分组计算，避免 4 万多次重复查技能/系别/克制。
        """
        if not candidates:
            return self._empty_result(observation, commit=commit)
        if observation.observation_type not in {
            ObservationType.DAMAGE_VALUE,
            ObservationType.HP_PERCENT_DELTA,
        }:
            return None

        payload = observation.payload
        if str(payload.get("formula_type", "attack") or "attack") != "attack":
            return None
        if str(payload.get("enemy_role", "defender")) != "defender":
            return None

        sample = candidates[0]
        sample_context = self.observation_matcher.build_damage_context_for_candidate_panel(
            observation=observation,
            candidate_elf_id=sample.elf_id,
            candidate_panel=self.observation_matcher._panel_from_candidate(sample),
            candidate_max_hp=sample.final_hp,
            resolve_rules=True,
        )
        sample_result = self.damage_calculator.calculate(sample_context)
        if sample_result.status != "calculated":
            if sample_result.missing_parts:
                return self._unknown_damage_result(
                    observation,
                    candidates,
                    missing_parts=sample_result.missing_parts,
                    commit=commit,
                )
            return None
        if sample_context.skill_category not in {"physical", "magic"}:
            return None

        grouped: dict[tuple[int, int, int], list[BuildCandidate]] = defaultdict(list)
        for candidate in candidates:
            grouped[
                (
                    candidate.final_hp,
                    candidate.final_physical_defense,
                    candidate.final_magic_defense,
                )
            ].append(candidate)

        matched_count = 0
        mismatched_count = 0
        unknown_count = 0
        hard_excluded_count = 0
        match_by_group: dict[tuple[int, int, int], ObservationMatchResult] = {}

        for key in grouped:
            hp, physical_defense, magic_defense = key
            context = sample_context.model_copy(
                deep=True,
                update={
                    "defender_panel_stats": PanelStats(
                        hp=hp,
                        physical_attack=sample.final_physical_attack,
                        physical_defense=physical_defense,
                        magic_attack=sample.final_magic_attack,
                        magic_defense=magic_defense,
                        speed=sample.final_speed,
                    ),
                    "defender_max_hp": hp,
                },
            )
            result = self.damage_calculator.calculate(context)
            match_result = self._match_grouped_damage_result(observation, result, hp)
            match_by_group[key] = match_result

        for key, rows in grouped.items():
            match_result = match_by_group[key]
            row_count = len(rows)
            if match_result.matched is True:
                matched_count += row_count
            elif match_result.matched is False:
                mismatched_count += row_count
            else:
                unknown_count += row_count

            for candidate in rows:
                self._apply_match_result(candidate, observation, match_result)
                if self._should_hard_exclude(observation, match_result):
                    candidate.is_excluded = True
                    candidate.excluded_reason = match_result.reason
                    hard_excluded_count += 1

        self._refresh_confidence_for_candidates(candidates)
        if commit:
            self.db.commit()

        top_candidate = self._top_candidate_from_rows(candidates)
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

    def _match_grouped_damage_result(
        self,
        observation: ObservationEventInput,
        result,
        max_hp: int,
    ) -> ObservationMatchResult:
        """按观测类型比较分组计算结果。"""
        if observation.observation_type == ObservationType.DAMAGE_VALUE:
            observed = observation.payload.get("observed_damage_value", observation.observed_value)
            return self.observation_matcher.damage_matcher.match_damage_value(
                observed=self.observation_matcher._optional_int(observed),
                result=result,
                tolerance=int(observation.payload.get("damage_tolerance", 0) or 0),
                event_weight=self.observation_matcher._event_weight(observation, 1.5),
            )

        observed = observation.payload.get("observed_hp_percent_delta", observation.observed_value)
        return self.observation_matcher.damage_matcher.match_hp_percent_delta(
            observed_pct=self.observation_matcher._optional_float(observed),
            result=result,
            max_hp=max_hp,
            tolerance=float(observation.payload.get("percent_tolerance", 1.0) or 1.0),
            event_weight=self.observation_matcher._event_weight(observation, 0.5),
        )

    def _should_hard_exclude(
        self,
        observation: ObservationEventInput,
        match_result: ObservationMatchResult,
    ) -> bool:
        """判断本次观测是否允许真正排除候选。

        当前只开放“单纯普通伤害”的硬排除：单次整数伤害、攻击公式、技能已确认、
        没有防御/减伤技能、三个应对均明确失败、无未知因素。其它情况仍保留软评分，
        避免未覆盖规则污染候选池。
        """
        if not observation.allow_hard_exclude or not match_result.can_hard_exclude:
            return False
        if observation.observation_type != ObservationType.DAMAGE_VALUE:
            return False
        if match_result.matched is not False:
            return False
        payload = observation.payload
        if str(payload.get("formula_type", "attack") or "attack") != "attack":
            return False
        damage_display_type = str(
            payload.get("damage_display_type", "single_damage") or "single_damage"
        )
        if damage_display_type != "single_damage":
            return False
        if not self._payload_bool(payload, "skill_confirmed", False):
            return False
        if not payload.get("skill_id"):
            return False
        if payload.get("defense_skill_id"):
            return False
        if payload.get("damage_reductions") or payload.get("damage_reduction_sources"):
            return False
        if match_result.unknown_factors:
            return False
        if payload.get("unknown_factors"):
            return False
        if payload.get("unstable_multiplier") not in (None, "", 1, 1.0, "1", "1.0"):
            return False
        for key in (
            "response_attack_success",
            "response_defense_success",
            "response_status_success",
        ):
            if self._optional_bool(payload.get(key)) is not False:
                return False
        return True

    def _empty_result(
        self,
        observation: ObservationEventInput,
        *,
        commit: bool,
    ) -> dict[str, Any]:
        """返回空候选池的稳定处理结果。"""
        if commit:
            self.db.commit()
        return {
            "status": "processed",
            "battle_id": observation.battle_id,
            "enemy_elf_id": observation.enemy_elf_id,
            "event_id": observation.event_id,
            "observation_type": observation.observation_type.value,
            "candidate_count": 0,
            "matched_count": 0,
            "mismatched_count": 0,
            "unknown_count": 0,
            "hard_excluded_count": 0,
            "hard_filter_applied": observation.allow_hard_exclude,
            "top_candidate_id": None,
            "top_confidence": None,
        }

    def _unknown_damage_result(
        self,
        observation: ObservationEventInput,
        candidates: list[BuildCandidate],
        *,
        missing_parts: list[str],
        commit: bool,
    ) -> dict[str, Any]:
        """公式关键上下文缺失时直接返回 unknown 摘要，避免全候选无意义写入。"""
        if commit:
            self.db.commit()
        top_candidate = self._top_candidate_from_rows(candidates)
        return {
            "status": "processed",
            "battle_id": observation.battle_id,
            "enemy_elf_id": observation.enemy_elf_id,
            "event_id": observation.event_id,
            "observation_type": observation.observation_type.value,
            "candidate_count": len(candidates),
            "matched_count": 0,
            "mismatched_count": 0,
            "unknown_count": len(candidates),
            "hard_excluded_count": 0,
            "hard_filter_applied": observation.allow_hard_exclude,
            "top_candidate_id": top_candidate.candidate_id if top_candidate else None,
            "top_confidence": top_candidate.confidence if top_candidate else None,
            "unknown_factors": missing_parts,
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
        self._refresh_confidence_for_candidates(candidates, temperature=temperature)

    @staticmethod
    def _refresh_confidence_for_candidates(
        candidates: list[BuildCandidate],
        temperature: float = 1.0,
    ) -> None:
        """按已加载候选池的 match_score 重新计算 softmax 置信度。"""
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
    def _top_candidate_from_rows(candidates: list[BuildCandidate]) -> BuildCandidate | None:
        """从已加载候选中取当前最高置信候选。"""
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                float(item.confidence or 0.0),
                float(item.match_score or 0.0),
            ),
        )

    @staticmethod
    def _optional_bool(value: Any) -> bool | None:
        """宽松解析可空布尔值；缺失时保留 None。"""
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    @classmethod
    def _payload_bool(cls, payload: dict[str, Any], key: str, default: bool) -> bool:
        """读取 payload 布尔值。"""
        parsed = cls._optional_bool(payload.get(key))
        return default if parsed is None else parsed

    @staticmethod
    def _append_json_list(raw_json: str | None, item: Any) -> str:
        """向候选 JSON 列表字段追加内容，并保持已有数据兼容。"""
        data = loads_json(raw_json, [])
        if not isinstance(data, list):
            data = []
        data.append(item)
        return dumps_json(data)
