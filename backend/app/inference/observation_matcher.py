"""观测事件总匹配器。

该模块是候选反推的分发层：InferenceEngine 不需要知道每种观测的细节，只需要把
候选、观测类型和 payload 交给 ObservationMatcher。后续增加伤害、状态、生存等 matcher
时，只需要扩展这里的分发逻辑。
"""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext, PanelStats
from app.calculation.rule_resolver import RuleResolver
from app.inference.damage_matcher import DamageMatcher
from app.inference.match_result import ObservationMatchResult
from app.inference.observation_types import ObservationType
from app.inference.skill_pool_matcher import SkillPoolMatcher
from app.inference.speed_matcher import SpeedMatcher
from app.models.candidate import BuildCandidate
from app.utils.json import loads_json


class ObservationEventInput(BaseModel):
    """InferenceEngine 消费的通用观测事件输入。"""

    battle_id: str
    enemy_elf_id: str
    event_id: str
    observation_type: ObservationType
    observed_value: int | float | str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    event_weight: float | None = None
    allow_hard_exclude: bool = False


class ObservationMatcher:
    """把通用观测事件分发到具体 matcher。"""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db
        self.skill_pool_matcher = SkillPoolMatcher()
        self.speed_matcher = SpeedMatcher()
        self.damage_calculator = DamageCalculator()
        self.damage_matcher = DamageMatcher()
        self.rule_resolver = RuleResolver(db)

    def match_candidate(
        self,
        *,
        observation: ObservationEventInput,
        candidate: BuildCandidate,
    ) -> ObservationMatchResult:
        """计算单个候选对当前观测事件的匹配结果。"""
        if observation.observation_type == ObservationType.SKILL_SEEN:
            return self._match_skill_seen(observation, candidate)
        if observation.observation_type == ObservationType.SPEED_ORDER:
            return self._match_speed_order(observation, candidate)
        if observation.observation_type == ObservationType.DAMAGE_VALUE:
            return self._match_damage_value(observation, candidate)
        if observation.observation_type == ObservationType.HP_PERCENT_DELTA:
            return self._match_hp_percent_delta(observation, candidate)

        # Milestone 2 暂不实现状态/生存匹配。返回 unknown 可以保证新入口安全接入，
        # 不会因为尚未支持的观测类型误扣分或误排除。
        return ObservationMatchResult.unknown_result(
            reason="observation_type_not_supported_yet",
            unknown_factors=[f"unsupported_observation_type:{observation.observation_type.value}"],
            observed_value=str(observation.observation_type),
        )

    def _match_skill_seen(
        self,
        observation: ObservationEventInput,
        candidate: BuildCandidate,
    ) -> ObservationMatchResult:
        raw_skill_id = observation.payload.get("skill_id") or observation.observed_value or ""
        skill_id = str(raw_skill_id) or None
        possible_skill_ids = loads_json(candidate.possible_skill_ids_json, None)
        if possible_skill_ids is not None and not isinstance(possible_skill_ids, list):
            possible_skill_ids = None
        return self.skill_pool_matcher.match_skill_seen(
            skill_id=skill_id,
            possible_skill_ids=possible_skill_ids,
            skill_pool_reliable=self._payload_bool(observation, "skill_pool_reliable", True),
            event_weight=self._event_weight(observation, 2.0),
        )

    def _match_speed_order(
        self,
        observation: ObservationEventInput,
        candidate: BuildCandidate,
    ) -> ObservationMatchResult:
        unknown_factors = observation.payload.get("unknown_factors") or []
        if not isinstance(unknown_factors, list):
            unknown_factors = [str(unknown_factors)]
        return self.speed_matcher.match_speed_order(
            observed_order=str(
                observation.payload.get("observed_order") or observation.observed_value or ""
            ),
            self_speed=observation.payload.get("self_speed"),
            candidate_speed=candidate.final_speed,
            unknown_factors=[str(item) for item in unknown_factors],
            event_weight=self._event_weight(observation, 1.0),
        )


    def _match_damage_value(
        self,
        observation: ObservationEventInput,
        candidate: BuildCandidate,
    ) -> ObservationMatchResult:
        context = self._build_damage_context(observation, candidate)
        result = self.damage_calculator.calculate(context)
        observed = observation.payload.get("observed_damage_value", observation.observed_value)
        return self.damage_matcher.match_damage_value(
            observed=self._optional_int(observed),
            result=result,
            tolerance=int(observation.payload.get("damage_tolerance", 0) or 0),
            event_weight=self._event_weight(observation, 1.5),
        )

    def _match_hp_percent_delta(
        self,
        observation: ObservationEventInput,
        candidate: BuildCandidate,
    ) -> ObservationMatchResult:
        context = self._build_damage_context(observation, candidate)
        result = self.damage_calculator.calculate(context)
        observed = observation.payload.get("observed_hp_percent_delta", observation.observed_value)
        max_hp = context.defender_max_hp
        return self.damage_matcher.match_hp_percent_delta(
            observed_pct=self._optional_float(observed),
            result=result,
            max_hp=max_hp,
            tolerance=float(observation.payload.get("percent_tolerance", 1.0) or 1.0),
            event_weight=self._event_weight(observation, 0.5),
        )

    def _build_damage_context(
        self,
        observation: ObservationEventInput,
        candidate: BuildCandidate,
    ) -> DamageFormulaContext:
        """用观测 payload 和候选面板组装最小伤害公式上下文。

        默认场景是“我方攻击，敌方作为防御方”，即候选面板替换 defender_panel_stats。
        若后续需要反推敌方作为攻击方，可在 payload 中传入 ``enemy_role='attacker'``。
        """
        payload = observation.payload
        enemy_role = str(payload.get("enemy_role", "defender"))
        candidate_panel = self._panel_from_candidate(candidate)
        provided_attacker = self._panel_from_payload(payload.get("attacker_panel_stats"))
        provided_defender = self._panel_from_payload(payload.get("defender_panel_stats"))

        if enemy_role == "attacker":
            attacker_panel = candidate_panel
            defender_panel = provided_defender
            defender_max_hp = self._optional_int(payload.get("defender_max_hp"))
            attacker_elf_id = candidate.elf_id
            defender_elf_id = self._optional_str(payload.get("defender_elf_id"))
        else:
            attacker_panel = provided_attacker
            defender_panel = candidate_panel
            defender_max_hp = candidate.final_hp
            attacker_elf_id = self._optional_str(payload.get("attacker_elf_id"))
            defender_elf_id = candidate.elf_id

        context = DamageFormulaContext(
            battle_id=observation.battle_id,
            damage_event_id=observation.event_id,
            formula_type="attack",
            attacker_side="enemy" if enemy_role == "attacker" else "self",
            defender_side="self" if enemy_role == "attacker" else "enemy",
            attacker_elf_id=attacker_elf_id,
            defender_elf_id=defender_elf_id,
            attacker_panel_stats=attacker_panel,
            defender_panel_stats=defender_panel,
            defender_max_hp=defender_max_hp,
            skill_id=self._optional_str(payload.get("skill_id")),
            skill_element_type=self._optional_str(payload.get("skill_element_type")),
            attacker_element_types=self._element_types_from_payload(payload.get("attacker_element_types")),
            defender_element_types=self._element_types_from_payload(payload.get("defender_element_types")),
            skill_category=self._optional_str(payload.get("skill_category")),
            base_power=payload.get("base_power"),
            display_power=payload.get("display_power"),
            response_multiplier=payload.get("response_multiplier", 1),
            flat_power_bonus=payload.get("flat_power_bonus", 0),
            power_multiplier=payload.get("power_multiplier", 1),
            stat_stage_multiplier=payload.get("stat_stage_multiplier", 1),
            stab_multiplier=payload.get("stab_multiplier", 1),
            type_multiplier=payload.get("type_multiplier", 1),
            weather_multiplier=payload.get("weather_multiplier", 1),
            unstable_multiplier=payload.get("unstable_multiplier", 1),
            damage_reductions=payload.get("damage_reductions", []) or [],
            hit_count=int(payload.get("hit_count", 1) or 1),
            observed_damage_value=self._optional_int(
                payload.get("observed_damage_value", observation.observed_value)
            ),
            observed_hp_percent_delta=self._optional_float(
                payload.get("observed_hp_percent_delta", observation.observed_value)
            ),
            unknown_factors=[str(item) for item in payload.get("unknown_factors", []) or []],
        )
        return self.rule_resolver.resolve_damage_context(context, payload)


    @staticmethod
    def _element_types_from_payload(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if item is not None and str(item)]
        return []

    @staticmethod
    def _panel_from_candidate(candidate: BuildCandidate) -> PanelStats:
        return PanelStats(
            hp=candidate.final_hp,
            physical_attack=candidate.final_physical_attack,
            physical_defense=candidate.final_physical_defense,
            magic_attack=candidate.final_magic_attack,
            magic_defense=candidate.final_magic_defense,
            speed=candidate.final_speed,
        )

    @staticmethod
    def _panel_from_payload(value: Any) -> PanelStats | None:
        if value is None:
            return None
        if isinstance(value, PanelStats):
            return value
        if not isinstance(value, dict):
            return None
        return PanelStats(**value)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        if value is None or value == "":
            return None
        return str(value)

    @staticmethod
    def _event_weight(observation: ObservationEventInput, default: float) -> float:
        """读取事件权重；显式传入 0 时也应被保留，不能被 ``or`` 覆盖。"""
        return default if observation.event_weight is None else observation.event_weight

    @staticmethod
    def _payload_bool(
        observation: ObservationEventInput,
        key: str,
        default: bool,
    ) -> bool:
        """宽松解析 payload 中的布尔配置，兼容前端传入字符串的情况。"""
        value = observation.payload.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)
