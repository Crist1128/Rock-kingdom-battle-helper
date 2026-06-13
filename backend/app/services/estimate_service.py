"""敌方面板实时估计服务。"""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.calculation.stat_calculator import (
    BaseTalentBlock,
    IndividualTalentDistribution,
    NatureRule,
    StatCalculator,
)
from app.core.enums import Side, StatKey
from app.inference.observation_event import ObservationEventInput
from app.inference.observation_payload import normalize_observation_payload
from app.inference.observation_types import ObservationType
from app.models.battle import BattleElfState
from app.models.estimate import EnemyPanelEstimate, EnemyPanelEstimateEvidence
from app.models.event import BattleEvent, DamageEvent
from app.models.static import ElfDefinition, NatureDefinition
from app.schemas.estimate import (
    EnemyDefaultConfigInput,
    EnemyPanelEstimateEvidenceOut,
    EnemyPanelEstimateOut,
)
from app.utils.json import dumps_json, loads_json


class EstimateService:
    """维护敌方精灵的实时面板估计档案。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_for_enemy_state(
        self,
        battle_id: str,
        state: BattleElfState,
        *,
        replace_existing: bool = False,
        commit: bool = False,
    ) -> EnemyPanelEstimate:
        """为敌方运行时状态创建一条空估计档案。"""
        if state.side != Side.ENEMY.value:
            raise ValueError("只有敌方精灵需要创建实时估计档案")
        if replace_existing:
            self.db.execute(
                delete(EnemyPanelEstimateEvidence).where(
                    EnemyPanelEstimateEvidence.battle_id == battle_id,
                    EnemyPanelEstimateEvidence.estimate_id.in_(
                        select(EnemyPanelEstimate.estimate_id).where(
                            EnemyPanelEstimate.battle_id == battle_id,
                            EnemyPanelEstimate.elf_id == state.elf_id,
                        )
                    ),
                )
            )
            self.db.execute(
                delete(EnemyPanelEstimate).where(
                    EnemyPanelEstimate.battle_id == battle_id,
                    EnemyPanelEstimate.elf_id == state.elf_id,
                )
            )

        existing = self._find_estimate(battle_id, state.elf_id)
        if existing is not None:
            return existing

        auto_default = self._build_auto_default_config(state.elf_id)
        estimate = EnemyPanelEstimate(
            estimate_id=f"enemy_panel_estimate_{uuid4().hex}",
            battle_id=battle_id,
            battle_elf_state_id=state.state_id,
            elf_id=state.elf_id,
            default_config_json=dumps_json(auto_default[0]) if auto_default is not None else None,
            default_panel_json=dumps_json(auto_default[1]) if auto_default is not None else None,
            estimated_panel_json=(
                dumps_json(auto_default[1])
                if auto_default is not None
                else self._base_talent_panel_json(state.elf_id)
            ),
            stat_constraints_json=dumps_json({}),
            confidence_json=dumps_json(
                {stat.value: "auto_default_config" for stat in StatKey}
                if auto_default is not None
                else {}
            ),
            unknown_factors_json=dumps_json(
                [
                    "默认面板来自种族值启发式配置，尚未由伤害、行动顺序或技能事件反推确认",
                ]
                if auto_default is not None
                else ["未选择默认配置，当前仅能展示种族值占位"]
            ),
            confirmed_skill_ids_json=dumps_json([]),
            evidence_summary_json=dumps_json([]),
            updated_by_event_id=None,
        )
        self.db.add(estimate)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(estimate)
        return estimate

    def get_estimate(self, battle_id: str, elf_id: str) -> EnemyPanelEstimateOut:
        """读取某只敌方精灵的当前估计档案。"""
        estimate = self._require_estimate(battle_id, elf_id)
        return self._to_out(estimate)

    def update_default_config(
        self,
        battle_id: str,
        elf_id: str,
        payload: EnemyDefaultConfigInput,
    ) -> EnemyPanelEstimateOut:
        """保存玩家选择的默认配置，并用它计算当前展示面板。"""
        estimate = self._require_estimate(battle_id, elf_id)
        elf = self._require_elf(elf_id)
        nature = self._require_nature(payload.nature_id)

        individual = IndividualTalentDistribution(
            **payload.individual_talent_distribution.model_dump()
        )
        panel = StatCalculator.calculate_panel_stats(
            base=self._elf_to_base_talent_block(elf),
            individual=individual,
            nature=self._nature_to_rule(nature),
        )
        stat_constraints = loads_json(estimate.stat_constraints_json, {}) or {}
        has_numeric_constraints = self._has_numeric_stat_constraints(stat_constraints)
        violations = self._panel_constraint_violations(panel.model_dump(), stat_constraints)
        if violations:
            failed_stats = "、".join(item["stat_key"] for item in violations)
            raise ValueError(f"默认配置不满足当前实时推导约束：{failed_stats}")

        default_config = {
            "preset": payload.preset,
            "nature_id": payload.nature_id,
            "individual_talent_distribution": individual.model_dump(),
        }
        estimate.default_config_json = dumps_json(default_config)
        estimate.default_panel_json = dumps_json(panel)
        estimate.estimated_panel_json = dumps_json(panel)
        if has_numeric_constraints:
            existing_unknowns = loads_json(estimate.unknown_factors_json, []) or []
            estimate.unknown_factors_json = dumps_json(
                self._append_unique_items(
                    existing_unknowns,
                    ["默认展示配置由玩家在当前实时推导约束内选择"],
                )
            )
        else:
            estimate.confidence_json = dumps_json(
                {stat.value: "default_config" for stat in StatKey}
            )
            estimate.unknown_factors_json = dumps_json(
                [
                    "该面板来自玩家默认配置，尚未由伤害、行动顺序或技能事件反推确认",
                ]
            )
        self.db.commit()
        self.db.refresh(estimate)
        return self._to_out(estimate)

    def list_evidence(
        self,
        battle_id: str,
        elf_id: str,
        *,
        limit: int = 50,
    ) -> list[EnemyPanelEstimateEvidenceOut]:
        """列出某只敌方精灵的实时估计证据。"""
        estimate = self._require_estimate(battle_id, elf_id)
        rows = self.db.scalars(
            select(EnemyPanelEstimateEvidence)
            .where(
                EnemyPanelEstimateEvidence.battle_id == battle_id,
                EnemyPanelEstimateEvidence.estimate_id == estimate.estimate_id,
            )
            .order_by(EnemyPanelEstimateEvidence.created_at.desc())
            .limit(limit)
        ).all()
        return [self._evidence_to_out(row) for row in rows]

    def rebuild_battle_estimates_from_events(
        self,
        battle_id: str,
        *,
        from_event_id: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """从当前非作废事件流重建本场战斗的敌方面板估计。

        这是估计层重放，不回滚或重演 BattleElfState、状态实例、资源变化等战斗运行时
        副作用。为了避免半量约束不可逆，当前会重建整场战斗的 estimate/evidence，
        `from_event_id` 仅作为触发与审计标识返回。
        """
        preserved_defaults = self._preserved_default_configs(battle_id)
        self.db.execute(
            delete(EnemyPanelEstimateEvidence).where(
                EnemyPanelEstimateEvidence.battle_id == battle_id
            )
        )
        self.db.execute(delete(EnemyPanelEstimate).where(EnemyPanelEstimate.battle_id == battle_id))

        enemy_states = list(
            self.db.scalars(
                select(BattleElfState)
                .where(
                    BattleElfState.battle_id == battle_id,
                    BattleElfState.side == Side.ENEMY.value,
                )
                .order_by(BattleElfState.created_at)
            ).all()
        )
        for state in enemy_states:
            estimate = self.create_for_enemy_state(battle_id, state, commit=False)
            preserved = preserved_defaults.get(state.elf_id)
            if preserved is not None:
                estimate.default_config_json = preserved.get("default_config_json")
                estimate.default_panel_json = preserved.get("default_panel_json")
                estimate.estimated_panel_json = preserved.get("default_panel_json")

        events = list(
            self.db.scalars(
                select(BattleEvent)
                .where(BattleEvent.battle_id == battle_id, BattleEvent.is_voided.is_(False))
                .order_by(BattleEvent.turn_number, BattleEvent.action_order, BattleEvent.created_at)
            ).all()
        )
        damage_by_battle_event_id = {
            item.battle_event_id: item
            for item in self.db.scalars(
                select(DamageEvent).where(DamageEvent.battle_id == battle_id)
            ).all()
        }

        replayed_observation_count = 0
        skipped_event_count = 0
        for event in events:
            observations = self._replay_observations_for_event(
                event,
                damage_by_battle_event_id.get(event.event_id),
            )
            if not observations:
                skipped_event_count += 1
                continue
            for observation in observations:
                if self.record_observation(observation, commit=False) is not None:
                    replayed_observation_count += 1

        if commit:
            self.db.commit()

        return {
            "battle_id": battle_id,
            "from_event_id": from_event_id,
            "status": "estimate_rebuilt",
            "replay_scope": "full_estimate_rebuild",
            "rebuilt_estimate_count": len(enemy_states),
            "replayed_event_count": len(events),
            "replayed_observation_count": replayed_observation_count,
            "skipped_event_count": skipped_event_count,
            "message": (
                "已重建实时面板估计和 evidence；本次未重演战斗状态、资源和状态实例副作用。"
            ),
        }

    def record_observation(
        self,
        observation: Any,
        *,
        inference_result: dict[str, Any] | None = None,
        commit: bool = False,
    ) -> EnemyPanelEstimateOut | None:
        """把一条 Observation 同步记录为实时估计证据。

        当前会记录观测证据，并在普通攻击最小公式上下文完整时写入低置信属性范围。
        """
        estimate = self._find_or_create_estimate_for_observation(
            str(observation.battle_id),
            str(observation.enemy_elf_id),
        )
        if estimate is None:
            return None

        observation_type = self._observation_type_value(observation.observation_type)
        payload = normalize_observation_payload(
            dict(getattr(observation, "payload", {}) or {}),
            observation_type=observation_type,
            observed_value=getattr(observation, "observed_value", None),
        )
        event_id = str(observation.event_id)
        constraint_delta = self._build_constraint_delta(
            observation_type=observation_type,
            event_id=event_id,
            payload=payload,
            observed_value=getattr(observation, "observed_value", None),
        )
        inferred_stats, reverse_unknowns = self._infer_stats_from_observation(
            observation_type=observation_type,
            payload=payload,
            observed_value=getattr(observation, "observed_value", None),
        )
        if inferred_stats:
            constraint_delta["status"] = "formula_constraint_derived"
            constraint_delta["derived_by"] = "minimal_attack_formula_reverse_v1"
            constraint_delta["inferred_stats"] = inferred_stats
        unknown_factors = self._observation_unknown_factors(
            observation_type=observation_type,
            payload=payload,
            reverse_unknowns=reverse_unknowns,
            has_inferred_stats=bool(inferred_stats),
        )

        stat_constraints = loads_json(estimate.stat_constraints_json, {}) or {}
        conflicts = self._merge_constraint_delta(stat_constraints, constraint_delta)
        if conflicts:
            constraint_delta["status"] = "constraint_conflict"
            constraint_delta["conflicts"] = conflicts
        estimate.stat_constraints_json = dumps_json(stat_constraints)

        confidence = loads_json(estimate.confidence_json, {}) or {}
        for stat_key in constraint_delta.get("affected_stats", []):
            confidence[str(stat_key)] = (
                "constraint_conflict"
                if any(item.get("stat_key") == str(stat_key) for item in conflicts)
                else
                "formula_constraint_derived"
                if str(stat_key) in inferred_stats
                else "observed_pending_formula"
            )
        estimate.confidence_json = dumps_json(confidence)

        confirmed_skill_ids = loads_json(estimate.confirmed_skill_ids_json, []) or []
        if observation_type == ObservationType.SKILL_SEEN.value:
            skill_id = payload.get("skill_id") or getattr(observation, "observed_value", None)
            if skill_id is not None and str(skill_id) not in confirmed_skill_ids:
                confirmed_skill_ids.append(str(skill_id))
        estimate.confirmed_skill_ids_json = dumps_json(confirmed_skill_ids)

        existing_unknowns = loads_json(estimate.unknown_factors_json, []) or []
        estimate.unknown_factors_json = dumps_json(
            self._append_unique_items(existing_unknowns, unknown_factors)
        )

        summary = loads_json(estimate.evidence_summary_json, []) or []
        summary.append(
            {
                "event_id": event_id,
                "observation_type": observation_type,
                "status": constraint_delta["status"],
                "affected_stats": constraint_delta.get("affected_stats", []),
                "inferred_stat_count": len(inferred_stats),
                "unknown_factor_count": len(unknown_factors),
            }
        )
        estimate.evidence_summary_json = dumps_json(summary[-10:])
        estimate.updated_by_event_id = event_id
        self._repair_default_config_if_needed(
            estimate,
            stat_constraints=stat_constraints,
            inferred_stats=inferred_stats,
        )

        self.db.add(
            EnemyPanelEstimateEvidence(
                evidence_id=f"enemy_panel_estimate_evidence_{uuid4().hex}",
                estimate_id=estimate.estimate_id,
                battle_id=estimate.battle_id,
                source_event_id=event_id,
                observation_type=observation_type,
                inferred_stats_json=dumps_json(inferred_stats),
                constraint_delta_json=dumps_json(constraint_delta),
                formula_context_json=dumps_json(
                    self._extract_formula_context(payload, inference_result or {})
                ),
                unknown_factors_json=dumps_json(unknown_factors),
                conflict_json=dumps_json({"conflicts": conflicts}) if conflicts else None,
                confidence=constraint_delta["status"],
            )
        )
        if commit:
            self.db.commit()
            self.db.refresh(estimate)
        return self._to_out(estimate)

    def _preserved_default_configs(self, battle_id: str) -> dict[str, dict[str, str | None]]:
        """重建 estimate 前保留玩家当前选择的默认展示配置。"""
        result: dict[str, dict[str, str | None]] = {}
        rows = self.db.scalars(
            select(EnemyPanelEstimate).where(EnemyPanelEstimate.battle_id == battle_id)
        ).all()
        for row in rows:
            if row.default_config_json is None and row.default_panel_json is None:
                continue
            result[row.elf_id] = {
                "default_config_json": row.default_config_json,
                "default_panel_json": row.default_panel_json,
            }
        return result

    def _replay_observations_for_event(
        self,
        event: BattleEvent,
        damage_event: DamageEvent | None,
    ) -> list[ObservationEventInput]:
        """把已落库战斗事件转换为估计层可消费的 observation。"""
        observations: list[ObservationEventInput] = []
        if event.event_type == "skill_use" and event.actor_side == Side.ENEMY.value:
            if event.actor_elf_id and event.skill_id:
                observations.append(
                    ObservationEventInput(
                        battle_id=event.battle_id,
                        enemy_elf_id=event.actor_elf_id,
                        event_id=f"replay:{event.event_id}:skill_seen",
                        observation_type=ObservationType.SKILL_SEEN,
                        observed_value=event.skill_id,
                        payload={
                            "skill_id": event.skill_id,
                            "source_battle_event_id": event.event_id,
                            "replay_source": "battle_event",
                        },
                    )
                )
        if damage_event is not None:
            observations.extend(self._replay_observations_for_damage_event(event, damage_event))
        return observations

    def _replay_observations_for_damage_event(
        self,
        event: BattleEvent,
        damage_event: DamageEvent,
    ) -> list[ObservationEventInput]:
        event_payload = loads_json(event.payload_json, {}) or {}
        if isinstance(event_payload, dict) and event_payload.get("sync_observation") is False:
            return []
        total_damage = self._replay_damage_value(damage_event)
        if total_damage is None or not damage_event.skill_id:
            return []

        enemy_role, enemy_elf_id = self._replay_enemy_observation_target(damage_event)
        if enemy_role is None or enemy_elf_id is None:
            return []

        formula_context = loads_json(damage_event.formula_context_json, {}) or {}
        if not isinstance(formula_context, dict):
            formula_context = {}
        damage_tolerance = self._non_negative_int(
            event_payload.get("damage_tolerance") if isinstance(event_payload, dict) else None,
            default=0,
        )
        percent_tolerance = self._decimal(
            event_payload.get("percent_tolerance") if isinstance(event_payload, dict) else None,
            default=Decimal("1"),
        )
        base_payload = {
            **formula_context,
            "enemy_role": enemy_role,
            "skill_confirmed": event.skill_confirmed,
            "damage_display_type": damage_event.damage_display_type,
            "damage_tolerance": damage_tolerance or 0,
            "percent_tolerance": float(percent_tolerance or Decimal("1")),
            "source_damage_event_id": damage_event.event_id,
            "source_battle_event_id": event.event_id,
            "replay_source": "battle_event",
        }

        observations = [
            ObservationEventInput(
                battle_id=event.battle_id,
                enemy_elf_id=enemy_elf_id,
                event_id=f"replay:{event.event_id}:damage_value",
                observation_type=ObservationType.DAMAGE_VALUE,
                observed_value=total_damage,
                payload=base_payload,
            )
        ]
        hp_percent_delta = damage_event.hp_percent_delta or damage_event.enemy_hp_percent_damage
        if enemy_role == "defender" and hp_percent_delta is not None:
            percent_payload = {
                **base_payload,
                "observed_hp_percent_before": damage_event.hp_percent_before,
                "observed_hp_percent_after": damage_event.hp_percent_after,
                "percent_display_mode": (
                    "floor_remaining_percent"
                    if self._is_integer_percent_pair(
                        damage_event.hp_percent_before,
                        damage_event.hp_percent_after,
                    )
                    else None
                ),
                "percent_tolerance": (
                    0
                    if self._is_integer_percent_pair(
                        damage_event.hp_percent_before,
                        damage_event.hp_percent_after,
                    )
                    else float(percent_tolerance or Decimal("1"))
                ),
            }
            observations.append(
                ObservationEventInput(
                    battle_id=event.battle_id,
                    enemy_elf_id=enemy_elf_id,
                    event_id=f"replay:{event.event_id}:hp_percent_delta",
                    observation_type=ObservationType.HP_PERCENT_DELTA,
                    observed_value=hp_percent_delta,
                    payload=percent_payload,
                )
            )
        return observations

    @staticmethod
    def _replay_damage_value(damage_event: DamageEvent) -> int | None:
        return (
            damage_event.damage_value
            or damage_event.computed_total_damage_value
            or damage_event.final_total_damage_value
        )

    @staticmethod
    def _replay_enemy_observation_target(
        damage_event: DamageEvent,
    ) -> tuple[str | None, str | None]:
        if damage_event.attacker_side == Side.ENEMY.value and damage_event.attacker_elf_id:
            return "attacker", damage_event.attacker_elf_id
        if damage_event.defender_side == Side.ENEMY.value and damage_event.defender_elf_id:
            return "defender", damage_event.defender_elf_id
        return None, None

    @staticmethod
    def _is_integer_percent_pair(before: float | None, after: float | None) -> bool:
        if before is None or after is None:
            return False
        return float(before).is_integer() and float(after).is_integer()

    def _base_talent_panel_json(self, elf_id: str) -> str:
        elf = self.db.get(ElfDefinition, elf_id)
        if elf is None:
            return dumps_json({})
        return dumps_json(
            {
                "hp": elf.base_hp_talent,
                "physical_attack": elf.base_physical_attack_talent,
                "physical_defense": elf.base_physical_defense_talent,
                "magic_attack": elf.base_magic_attack_talent,
                "magic_defense": elf.base_magic_defense_talent,
                "speed": elf.base_speed_talent,
                "source": "base_talent_only",
            }
        )

    def _build_auto_default_config(
        self,
        elf_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """按种族值启发式生成敌方未知面板的默认展示配置。"""
        elf = self.db.get(ElfDefinition, elf_id)
        if elf is None or elf.deleted_at is not None:
            return None

        uses_physical = elf.base_physical_attack_talent > elf.base_magic_attack_talent
        is_fast = elf.base_speed_talent >= 115
        if is_fast:
            positive_stat = StatKey.SPEED
            negative_stat = StatKey.MAGIC_ATTACK if uses_physical else StatKey.PHYSICAL_ATTACK
        else:
            positive_stat = StatKey.PHYSICAL_ATTACK if uses_physical else StatKey.MAGIC_ATTACK
            negative_stat = StatKey.MAGIC_ATTACK if uses_physical else StatKey.PHYSICAL_ATTACK

        nature = self.db.scalars(
            select(NatureDefinition).where(
                NatureDefinition.positive_stat == positive_stat.value,
                NatureDefinition.negative_stat == negative_stat.value,
                NatureDefinition.deleted_at.is_(None),
            )
        ).first()
        if nature is None:
            return None

        talents = {stat.value: 0 for stat in StatKey}
        talents[StatKey.HP.value] = 10
        talents[StatKey.SPEED.value] = 10
        talents[
            StatKey.PHYSICAL_ATTACK.value if uses_physical else StatKey.MAGIC_ATTACK.value
        ] = 10
        individual = IndividualTalentDistribution(**talents)
        panel = StatCalculator.calculate_panel_stats(
            base=self._elf_to_base_talent_block(elf),
            individual=individual,
            nature=self._nature_to_rule(nature),
        )
        return (
            {
                "preset": "auto_by_base_stats",
                "nature_id": nature.nature_id,
                "individual_talent_distribution": individual.model_dump(),
                "heuristic": {
                    "uses_physical": uses_physical,
                    "speed_threshold": 115,
                    "base_physical_attack_talent": elf.base_physical_attack_talent,
                    "base_magic_attack_talent": elf.base_magic_attack_talent,
                    "base_speed_talent": elf.base_speed_talent,
                },
            },
            {**panel.model_dump(), "source": "auto_default_config"},
        )

    def _find_estimate(self, battle_id: str, elf_id: str) -> EnemyPanelEstimate | None:
        return self.db.scalars(
            select(EnemyPanelEstimate).where(
                EnemyPanelEstimate.battle_id == battle_id,
                EnemyPanelEstimate.elf_id == elf_id,
                EnemyPanelEstimate.deleted_at.is_(None),
            )
        ).first()

    def _find_or_create_estimate_for_observation(
        self,
        battle_id: str,
        elf_id: str,
    ) -> EnemyPanelEstimate | None:
        estimate = self._find_estimate(battle_id, elf_id)
        if estimate is not None:
            return estimate
        state = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == battle_id,
                BattleElfState.side == Side.ENEMY.value,
                BattleElfState.elf_id == elf_id,
            )
        ).first()
        if state is None:
            return None
        return self.create_for_enemy_state(battle_id, state, commit=False)

    def _require_estimate(self, battle_id: str, elf_id: str) -> EnemyPanelEstimate:
        estimate = self._find_estimate(battle_id, elf_id)
        if estimate is not None:
            return estimate

        state = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == battle_id,
                BattleElfState.side == Side.ENEMY.value,
                BattleElfState.elf_id == elf_id,
            )
        ).first()
        if state is None:
            raise LookupError(f"敌方精灵不在该战斗阵容中：{elf_id}")
        return self.create_for_enemy_state(battle_id, state, commit=True)

    def _require_elf(self, elf_id: str) -> ElfDefinition:
        elf = self.db.get(ElfDefinition, elf_id)
        if elf is None or elf.deleted_at is not None:
            raise ValueError(f"精灵不存在：{elf_id}")
        return elf

    def _require_nature(self, nature_id: str) -> NatureDefinition:
        nature = self.db.get(NatureDefinition, nature_id)
        if nature is None or nature.deleted_at is not None:
            raise ValueError(f"性格不存在：{nature_id}")
        return nature

    @staticmethod
    def _elf_to_base_talent_block(elf: ElfDefinition) -> BaseTalentBlock:
        return BaseTalentBlock(
            hp=elf.base_hp_talent,
            physical_attack=elf.base_physical_attack_talent,
            physical_defense=elf.base_physical_defense_talent,
            magic_attack=elf.base_magic_attack_talent,
            magic_defense=elf.base_magic_defense_talent,
            speed=elf.base_speed_talent,
        )

    @staticmethod
    def _nature_to_rule(nature: NatureDefinition) -> NatureRule:
        return NatureRule(
            nature_id=nature.nature_id,
            positive_stat=StatKey(nature.positive_stat),
            negative_stat=StatKey(nature.negative_stat),
        )

    @staticmethod
    def _to_out(estimate: EnemyPanelEstimate) -> EnemyPanelEstimateOut:
        return EnemyPanelEstimateOut(
            estimate_id=estimate.estimate_id,
            battle_id=estimate.battle_id,
            battle_elf_state_id=estimate.battle_elf_state_id,
            elf_id=estimate.elf_id,
            default_config=loads_json(estimate.default_config_json, None),
            default_panel=loads_json(estimate.default_panel_json, None),
            estimated_panel=loads_json(estimate.estimated_panel_json, None),
            stat_constraints=loads_json(estimate.stat_constraints_json, {}) or {},
            confidence=loads_json(estimate.confidence_json, {}) or {},
            unknown_factors=loads_json(estimate.unknown_factors_json, []) or [],
            confirmed_skill_ids=loads_json(estimate.confirmed_skill_ids_json, []) or [],
            evidence_summary=loads_json(estimate.evidence_summary_json, []) or [],
            updated_by_event_id=estimate.updated_by_event_id,
        )

    @staticmethod
    def _evidence_to_out(
        evidence: EnemyPanelEstimateEvidence,
    ) -> EnemyPanelEstimateEvidenceOut:
        return EnemyPanelEstimateEvidenceOut(
            evidence_id=evidence.evidence_id,
            estimate_id=evidence.estimate_id,
            battle_id=evidence.battle_id,
            source_event_id=evidence.source_event_id,
            observation_type=evidence.observation_type,
            inferred_stats=loads_json(evidence.inferred_stats_json, None),
            constraint_delta=loads_json(evidence.constraint_delta_json, None),
            formula_context=loads_json(evidence.formula_context_json, None),
            explanation=EstimateService._build_evidence_explanation(evidence),
            unknown_factors=loads_json(evidence.unknown_factors_json, []) or [],
            conflict=loads_json(evidence.conflict_json, None),
            confidence=evidence.confidence,
        )

    @staticmethod
    def _observation_type_value(observation_type: Any) -> str:
        if hasattr(observation_type, "value"):
            return str(observation_type.value)
        return str(observation_type)

    @classmethod
    def _build_constraint_delta(
        cls,
        *,
        observation_type: str,
        event_id: str,
        payload: dict[str, Any],
        observed_value: Any,
    ) -> dict[str, Any]:
        affected_stats = cls._affected_stats_for_observation(observation_type, payload)
        return {
            "event_id": event_id,
            "observation_type": observation_type,
            "status": "recorded_pending_formula",
            "affected_stats": affected_stats,
            "observed_value": observed_value,
            "enemy_role": payload.get("enemy_role"),
            "skill_category": payload.get("skill_category"),
            "note": "当前仅记录观测事实和待推导属性，不直接反推出确定面板值。",
        }

    @staticmethod
    def _affected_stats_for_observation(
        observation_type: str,
        payload: dict[str, Any],
    ) -> list[str]:
        if observation_type == ObservationType.SKILL_SEEN.value:
            return []
        if observation_type == ObservationType.SPEED_ORDER.value:
            return [StatKey.SPEED.value]
        if observation_type not in {
            ObservationType.DAMAGE_VALUE.value,
            ObservationType.HP_PERCENT_DELTA.value,
        }:
            return []

        enemy_role = str(payload.get("enemy_role", "defender") or "defender")
        skill_category = str(payload.get("skill_category", "") or "")
        if enemy_role == "attacker":
            if skill_category == "physical":
                return [StatKey.PHYSICAL_ATTACK.value]
            if skill_category == "magic":
                return [StatKey.MAGIC_ATTACK.value]
            return [StatKey.PHYSICAL_ATTACK.value, StatKey.MAGIC_ATTACK.value]

        stats = [StatKey.HP.value]
        if skill_category == "physical":
            stats.append(StatKey.PHYSICAL_DEFENSE.value)
        elif skill_category == "magic":
            stats.append(StatKey.MAGIC_DEFENSE.value)
        else:
            stats.extend([StatKey.PHYSICAL_DEFENSE.value, StatKey.MAGIC_DEFENSE.value])
        return stats

    @classmethod
    def _merge_constraint_delta(
        cls,
        stat_constraints: dict[str, Any],
        constraint_delta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        constraint_effects: list[dict[str, Any]] = []
        history = stat_constraints.setdefault("observation_history", [])
        if isinstance(history, list):
            history.append(constraint_delta)
            stat_constraints["observation_history"] = history[-20:]
        for stat_key in constraint_delta.get("affected_stats", []):
            stat_entry = stat_constraints.setdefault(str(stat_key), {})
            if not isinstance(stat_entry, dict):
                stat_entry = {}
                stat_constraints[str(stat_key)] = stat_entry
            event_ids = stat_entry.setdefault("source_event_ids", [])
            if isinstance(event_ids, list) and constraint_delta["event_id"] not in event_ids:
                event_ids.append(constraint_delta["event_id"])
            inferred_stats = constraint_delta.get("inferred_stats", {})
            inferred_entry = (
                inferred_stats.get(str(stat_key)) if isinstance(inferred_stats, dict) else None
            )
            before = cls._constraint_range_snapshot(stat_entry)
            if isinstance(inferred_entry, dict):
                incoming = cls._constraint_range_snapshot(inferred_entry)
                conflict = cls._merge_numeric_range(stat_entry, inferred_entry)
                stat_entry.update(inferred_entry)
                if conflict is not None:
                    conflict["stat_key"] = str(stat_key)
                    conflicts.append(conflict)
                    stat_entry["status"] = "constraint_conflict"
                    stat_entry["latest_conflict"] = conflict
                    outcome = "conflict"
                else:
                    stat_entry["status"] = "formula_constraint_derived"
                    outcome = cls._constraint_change_outcome(before, stat_entry)
            else:
                stat_entry["status"] = "observed_pending_formula"
                incoming = None
                outcome = "recorded_without_numeric_constraint"
            stat_entry["last_observation_type"] = constraint_delta["observation_type"]
            constraint_effects.append(
                {
                    "stat_key": str(stat_key),
                    "outcome": outcome,
                    "previous": before,
                    "incoming": incoming,
                    "merged": cls._constraint_range_snapshot(stat_entry),
                    "source_event_ids": list(event_ids) if isinstance(event_ids, list) else [],
                }
            )
        constraint_delta["constraint_effects"] = constraint_effects
        return conflicts

    @staticmethod
    def _constraint_range_snapshot(entry: dict[str, Any] | None) -> dict[str, Any]:
        """抽取前端解释需要的约束快照，避免展示整段内部 JSON。"""
        if not isinstance(entry, dict):
            return {}
        keys = (
            "status",
            "integer_min",
            "integer_max",
            "min",
            "max",
            "confidence",
            "source",
            "relation",
        )
        return {key: entry[key] for key in keys if key in entry}

    @staticmethod
    def _constraint_change_outcome(
        before: dict[str, Any],
        merged: dict[str, Any],
    ) -> str:
        if not before:
            return "new_constraint"
        before_min = before.get("integer_min")
        before_max = before.get("integer_max")
        merged_min = merged.get("integer_min")
        merged_max = merged.get("integer_max")
        if before_min == merged_min and before_max == merged_max:
            return "confirmed_existing_constraint"
        return "narrowed_constraint"

    @classmethod
    def _merge_numeric_range(
        cls,
        current: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any] | None:
        """同一属性多条整数约束取交集，避免宽范围覆盖窄范围。"""
        current_min = cls._non_negative_int(current.get("integer_min"), default=None)
        current_max = cls._non_negative_int(current.get("integer_max"), default=None)
        incoming_min = cls._non_negative_int(incoming.get("integer_min"), default=None)
        incoming_max = cls._non_negative_int(incoming.get("integer_max"), default=None)
        if current_min is not None and incoming_min is not None:
            incoming["integer_min"] = max(current_min, incoming_min)
        if current_max is not None and incoming_max is not None:
            incoming["integer_max"] = min(current_max, incoming_max)
        if (
            incoming.get("integer_min") is not None
            and incoming.get("integer_max") is not None
            and int(incoming["integer_min"]) > int(incoming["integer_max"])
        ):
            incoming["status"] = "constraint_conflict"
            return {
                "reason": "numeric_range_intersection_empty",
                "current_integer_min": current_min,
                "current_integer_max": current_max,
                "incoming_integer_min": incoming_min,
                "incoming_integer_max": incoming_max,
                "merged_integer_min": incoming["integer_min"],
                "merged_integer_max": incoming["integer_max"],
            }
        return None

    @classmethod
    def _observation_unknown_factors(
        cls,
        *,
        observation_type: str,
        payload: dict[str, Any],
        reverse_unknowns: list[str] | None = None,
        has_inferred_stats: bool = False,
    ) -> list[str]:
        unknowns = [str(item) for item in payload.get("unknown_factors", []) or []]
        if observation_type in {
            ObservationType.DAMAGE_VALUE.value,
            ObservationType.HP_PERCENT_DELTA.value,
        }:
            if reverse_unknowns:
                unknowns.extend(reverse_unknowns)
            if not has_inferred_stats and not reverse_unknowns:
                unknowns.append("damage_formula_reverse_inference_context_incomplete")
            unknowns.extend(cls._modifier_unknown_factors(payload))
        if observation_type == ObservationType.SPEED_ORDER.value:
            unknowns.append("speed_tie_and_priority_rule_not_confirmed")
        return cls._append_unique_items([], unknowns)

    @classmethod
    def _infer_stats_from_observation(
        cls,
        *,
        observation_type: str,
        payload: dict[str, Any],
        observed_value: Any,
    ) -> tuple[dict[str, Any], list[str]]:
        """基于已验证的普通攻击最小公式反推低置信属性范围。"""
        if observation_type not in {
            ObservationType.DAMAGE_VALUE.value,
            ObservationType.HP_PERCENT_DELTA.value,
        }:
            return {}, []

        formula_type = str(payload.get("formula_type", "attack") or "attack")
        if formula_type == "status":
            return cls._infer_stats_from_status_observation(
                observation_type=observation_type,
                payload=payload,
                observed_value=observed_value,
            )
        if formula_type != "attack":
            return {}, ["reverse_inference_only_supports_attack_formula"]

        inferred: dict[str, Any] = {}
        unknowns: list[str] = []
        damage_value = cls._observed_damage_value(
            observation_type=observation_type,
            payload=payload,
            observed_value=observed_value,
        )
        if damage_value is None:
            unknowns.append("observed_damage_value_missing_for_reverse_inference")
        else:
            stat_range, range_unknowns = cls._infer_attack_or_defense_range(
                payload=payload,
                observed_damage=damage_value,
            )
            inferred.update(stat_range)
            unknowns.extend(range_unknowns)

            hp_range = cls._infer_hp_range(
                observation_type=observation_type,
                payload=payload,
                observed_value=observed_value,
                observed_damage=damage_value,
            )
            if hp_range is not None:
                inferred[StatKey.HP.value] = hp_range

        return inferred, cls._append_unique_items([], unknowns)

    @classmethod
    def _infer_stats_from_status_observation(
        cls,
        *,
        observation_type: str,
        payload: dict[str, Any],
        observed_value: Any,
    ) -> tuple[dict[str, Any], list[str]]:
        """用状态结算的伤害值、层数、克制倍率和血条百分比反推敌方 HP。"""
        damage_value = cls._observed_damage_value(
            observation_type=observation_type,
            payload=payload,
            observed_value=observed_value,
        )
        if damage_value is None:
            return {}, ["observed_damage_value_missing_for_status_reverse_inference"]

        unknowns: list[str] = []
        formula_range, formula_unknowns = cls._infer_status_formula_hp_range(
            payload=payload,
            observed_damage=damage_value,
        )
        unknowns.extend(formula_unknowns)
        percent_range = cls._infer_hp_range(
            observation_type=observation_type,
            payload=payload,
            observed_value=observed_value,
            observed_damage=damage_value,
        )
        hp_range = cls._intersect_hp_ranges(
            formula_range,
            percent_range,
            observed_damage=damage_value,
        )
        inferred = {StatKey.HP.value: hp_range} if hp_range is not None else {}
        return inferred, cls._append_unique_items([], unknowns)

    @classmethod
    def _infer_status_formula_hp_range(
        cls,
        *,
        payload: dict[str, Any],
        observed_damage: int,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        percent_per_layer = cls._status_percent_per_layer(payload)
        if percent_per_layer is None or percent_per_layer <= 0:
            return None, ["status_percent_per_layer_missing_for_reverse_inference"]
        layers = cls._positive_int(payload.get("effect_layers"), default=1)
        type_multiplier = cls._decimal(payload.get("type_multiplier"), default=Decimal("1"))
        factor = percent_per_layer * Decimal(layers) * (type_multiplier or Decimal("1"))
        if factor <= 0:
            return None, ["status_damage_factor_invalid_for_reverse_inference"]

        lower = Decimal(observed_damage) / factor
        upper_exclusive = Decimal(observed_damage + 1) / factor
        result = cls._range_payload(
            lower=lower,
            upper=upper_exclusive,
            source="status_damage_formula_reverse",
            relation="hp_range_from_status_damage_formula",
            observed_damage=observed_damage,
            hit_count=1,
            formula_factor=factor,
        )
        result["integer_max"] = cls._ceil_decimal(upper_exclusive) - 1
        result["max_exclusive"] = str(upper_exclusive.quantize(Decimal("0.0001")))
        result["effect_id"] = payload.get("effect_id")
        result["effect_layers"] = layers
        result["status_percent_per_layer"] = str(percent_per_layer)
        result["type_multiplier"] = str(type_multiplier or Decimal("1"))
        return result, []

    @staticmethod
    def _status_percent_per_layer(payload: dict[str, Any]) -> Decimal | None:
        value = payload.get("status_percent_per_layer")
        if value is None:
            value = payload.get("percent_per_layer")
        if value is None:
            defaults = {
                "effect_burn": "0.02",
                "burn": "0.02",
                "effect_poison": "0.03",
                "poison": "0.03",
                "effect_poison_mark": "0.03",
                "poison_mark": "0.03",
                "effect_thorn_mark": "0.06",
                "thorn_mark": "0.06",
                "thorn": "0.06",
            }
            value = defaults.get(str(payload.get("effect_id") or ""))
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @classmethod
    def _intersect_hp_ranges(
        cls,
        first: dict[str, Any] | None,
        second: dict[str, Any] | None,
        *,
        observed_damage: int,
    ) -> dict[str, Any] | None:
        if first is None:
            return second
        if second is None:
            return first
        lower = max(
            cls._decimal(first.get("min"), default=Decimal("0")) or Decimal("0"),
            cls._decimal(second.get("min"), default=Decimal("0")) or Decimal("0"),
        )
        first_upper = cls._decimal(
            first.get("max_exclusive") or first.get("max"),
            default=None,
        )
        second_upper = cls._decimal(
            second.get("max_exclusive") or second.get("max"),
            default=None,
        )
        if first_upper is None:
            upper = second_upper
        elif second_upper is None:
            upper = first_upper
        else:
            upper = min(first_upper, second_upper)
        if upper is None or upper <= lower:
            return first
        result = cls._range_payload(
            lower=lower,
            upper=upper,
            source="status_damage_formula_and_percent_reverse",
            relation="hp_range_intersection_from_status_damage_and_hp_percent",
            observed_damage=observed_damage,
            hit_count=1,
            formula_factor=cls._decimal(first.get("formula_factor"), default=None),
        )
        result["integer_max"] = min(
            int(first.get("integer_max", result["integer_max"])),
            int(second.get("integer_max", result["integer_max"])),
        )
        result["components"] = [first.get("source"), second.get("source")]
        return result

    @classmethod
    def _infer_attack_or_defense_range(
        cls,
        *,
        payload: dict[str, Any],
        observed_damage: int,
    ) -> tuple[dict[str, Any], list[str]]:
        skill_category = str(payload.get("skill_category", "") or "")
        if skill_category not in {"physical", "magic"}:
            return {}, ["skill_category_missing_for_reverse_inference"]

        factor = cls._attack_formula_factor(payload)
        if factor is None or factor <= 0:
            return {}, ["attack_formula_factor_missing_for_reverse_inference"]

        hit_count = cls._positive_int(payload.get("hit_count"), default=1)
        tolerance = cls._non_negative_int(payload.get("damage_tolerance"), default=0)
        total_low = max(observed_damage - tolerance, 0)
        total_high = observed_damage + tolerance
        single_low = cls._ceil_decimal(Decimal(total_low) / Decimal(hit_count))
        single_high = cls._floor_decimal(Decimal(total_high) / Decimal(hit_count))
        if single_high < single_low or single_high <= 0:
            return {}, ["zero_or_invalid_damage_range_for_reverse_inference"]

        ratio_min = Decimal(single_low) / factor
        ratio_max_exclusive = Decimal(single_high + 1) / factor
        if ratio_min <= 0 or ratio_max_exclusive <= 0:
            return {}, ["invalid_attack_defense_ratio_for_reverse_inference"]

        enemy_role = str(payload.get("enemy_role", "defender") or "defender")
        if enemy_role == "attacker":
            return cls._infer_enemy_offense_range(
                payload=payload,
                skill_category=skill_category,
                ratio_min=ratio_min,
                ratio_max_exclusive=ratio_max_exclusive,
                observed_damage=observed_damage,
                hit_count=hit_count,
                factor=factor,
            )
        return cls._infer_enemy_defense_range(
            payload=payload,
            skill_category=skill_category,
            ratio_min=ratio_min,
            ratio_max_exclusive=ratio_max_exclusive,
            observed_damage=observed_damage,
            hit_count=hit_count,
            factor=factor,
        )

    @classmethod
    def _infer_enemy_defense_range(
        cls,
        *,
        payload: dict[str, Any],
        skill_category: str,
        ratio_min: Decimal,
        ratio_max_exclusive: Decimal,
        observed_damage: int,
        hit_count: int,
        factor: Decimal,
    ) -> tuple[dict[str, Any], list[str]]:
        offense_stat = (
            StatKey.PHYSICAL_ATTACK.value
            if skill_category == "physical"
            else StatKey.MAGIC_ATTACK.value
        )
        defense_stat = (
            StatKey.PHYSICAL_DEFENSE.value
            if skill_category == "physical"
            else StatKey.MAGIC_DEFENSE.value
        )
        offense = cls._panel_stat(payload.get("attacker_panel_stats"), offense_stat)
        if offense is None or offense <= 0:
            return {}, ["known_attacker_offense_missing_for_reverse_inference"]

        lower = offense / ratio_max_exclusive
        upper = offense / ratio_min
        return {
            defense_stat: cls._range_payload(
                lower=lower,
                upper=upper,
                source="observed_damage_reverse_attack_formula",
                relation="defense_range_from_known_offense",
                observed_damage=observed_damage,
                hit_count=hit_count,
                formula_factor=factor,
            )
        }, []

    @classmethod
    def _infer_enemy_offense_range(
        cls,
        *,
        payload: dict[str, Any],
        skill_category: str,
        ratio_min: Decimal,
        ratio_max_exclusive: Decimal,
        observed_damage: int,
        hit_count: int,
        factor: Decimal,
    ) -> tuple[dict[str, Any], list[str]]:
        offense_stat = (
            StatKey.PHYSICAL_ATTACK.value
            if skill_category == "physical"
            else StatKey.MAGIC_ATTACK.value
        )
        defense_stat = (
            StatKey.PHYSICAL_DEFENSE.value
            if skill_category == "physical"
            else StatKey.MAGIC_DEFENSE.value
        )
        defense = cls._panel_stat(payload.get("defender_panel_stats"), defense_stat)
        if defense is None or defense <= 0:
            return {}, ["known_defender_defense_missing_for_reverse_inference"]

        lower = defense * ratio_min
        upper = defense * ratio_max_exclusive
        return {
            offense_stat: cls._range_payload(
                lower=lower,
                upper=upper,
                source="observed_damage_reverse_attack_formula",
                relation="offense_range_from_known_defense",
                observed_damage=observed_damage,
                hit_count=hit_count,
                formula_factor=factor,
            )
        }, []

    @classmethod
    def _infer_hp_range(
        cls,
        *,
        observation_type: str,
        payload: dict[str, Any],
        observed_value: Any,
        observed_damage: int,
    ) -> dict[str, Any] | None:
        floor_range = cls._infer_hp_range_from_floor_remaining_percent(
            payload=payload,
            observed_damage=observed_damage,
        )
        if floor_range is not None:
            return floor_range

        pct = cls._observed_hp_percent_delta(
            observation_type=observation_type,
            payload=payload,
            observed_value=observed_value,
        )
        if pct is None or pct <= 0:
            return None
        tolerance = cls._decimal(payload.get("percent_tolerance"), default=Decimal("1"))
        lower_pct = max(pct - tolerance, Decimal("0.0001"))
        upper_pct = pct + tolerance
        lower = Decimal(observed_damage) * Decimal(100) / upper_pct
        upper = Decimal(observed_damage) * Decimal(100) / lower_pct
        return cls._range_payload(
            lower=lower,
            upper=upper,
            source="damage_and_hp_percent_reverse",
            relation="hp_range_from_damage_percent_delta",
            observed_damage=observed_damage,
            hit_count=cls._positive_int(payload.get("hit_count"), default=1),
            formula_factor=None,
        )

    @classmethod
    def _infer_hp_range_from_floor_remaining_percent(
        cls,
        *,
        payload: dict[str, Any],
        observed_damage: int,
    ) -> dict[str, Any] | None:
        display_mode = str(payload.get("percent_display_mode", "") or "")
        if display_mode != "floor_remaining_percent":
            return None
        before = cls._decimal(payload.get("observed_hp_percent_before"), default=None)
        after = cls._decimal(payload.get("observed_hp_percent_after"), default=None)
        if before is None or after is None:
            return None
        if observed_damage <= 0 or before <= after:
            return None

        actual_after_min = after
        actual_after_max_exclusive = after + Decimal("1")
        actual_delta_min_exclusive = before - actual_after_max_exclusive
        actual_delta_max = before - actual_after_min
        if actual_delta_max <= 0:
            return None

        lower_pct_exclusive = max(actual_delta_min_exclusive, Decimal("0.0001"))
        upper_pct_inclusive = actual_delta_max
        lower = Decimal(observed_damage) * Decimal(100) / upper_pct_inclusive
        upper_exclusive = Decimal(observed_damage) * Decimal(100) / lower_pct_exclusive
        result = cls._range_payload(
            lower=lower,
            upper=upper_exclusive,
            source="damage_and_floor_remaining_percent_reverse",
            relation="hp_range_from_displayed_remaining_percent",
            observed_damage=observed_damage,
            hit_count=cls._positive_int(payload.get("hit_count"), default=1),
            formula_factor=None,
        )
        result["integer_max"] = cls._ceil_decimal(upper_exclusive) - 1
        result["max_exclusive"] = str(upper_exclusive.quantize(Decimal("0.0001")))
        result["display_remaining_percent"] = int(after)
        return result

    @classmethod
    def _attack_formula_factor(cls, payload: dict[str, Any]) -> Decimal | None:
        display_power = cls._decimal(payload.get("display_power"), default=None)
        if display_power is None:
            base_power = cls._decimal(payload.get("base_power"), default=None)
            if base_power is None:
                return None
            display_power = (
                base_power
                * cls._decimal(payload.get("response_multiplier"), default=Decimal("1"))
                + cls._decimal(payload.get("flat_power_bonus"), default=Decimal("0"))
            )
            display_power *= cls._decimal(payload.get("power_multiplier"), default=Decimal("1"))
            display_power *= cls._decimal(
                payload.get("stat_stage_multiplier"),
                default=Decimal("1"),
            )
            display_power *= cls._decimal(payload.get("stab_multiplier"), default=Decimal("1"))
            display_power *= cls._decimal(payload.get("type_multiplier"), default=Decimal("1"))
            display_power *= cls._decimal(
                payload.get("weather_multiplier"),
                default=Decimal("1"),
            )

        reduction_product = Decimal("1")
        for item in payload.get("damage_reductions", []) or []:
            reduction = cls._decimal(item, default=None)
            if reduction is None:
                return None
            reduction_product *= Decimal("1") - reduction
        unstable = cls._decimal(payload.get("unstable_multiplier"), default=Decimal("1"))
        return display_power * unstable * reduction_product * Decimal(37) / Decimal(41)

    @staticmethod
    def _range_payload(
        *,
        lower: Decimal,
        upper: Decimal,
        source: str,
        relation: str,
        observed_damage: int,
        hit_count: int,
        formula_factor: Decimal | None,
    ) -> dict[str, Any]:
        return {
            "min": str(lower.quantize(Decimal("0.0001"))),
            "max": str(upper.quantize(Decimal("0.0001"))),
            "integer_min": int(lower.to_integral_value(rounding=ROUND_CEILING)),
            "integer_max": int(upper.to_integral_value(rounding=ROUND_FLOOR)),
            "source": source,
            "relation": relation,
            "confidence": "low",
            "observed_damage": observed_damage,
            "hit_count": hit_count,
            "formula_factor": (
                str(formula_factor.quantize(Decimal("0.0001")))
                if formula_factor is not None
                else None
            ),
        }

    @classmethod
    def _observed_damage_value(
        cls,
        *,
        observation_type: str,
        payload: dict[str, Any],
        observed_value: Any,
    ) -> int | None:
        value = payload.get("observed_damage_value")
        if value is None and observation_type == ObservationType.DAMAGE_VALUE.value:
            value = observed_value
        return cls._non_negative_int(value, default=None)

    @classmethod
    def _observed_hp_percent_delta(
        cls,
        *,
        observation_type: str,
        payload: dict[str, Any],
        observed_value: Any,
    ) -> Decimal | None:
        value = payload.get("observed_hp_percent_delta")
        if value is None and observation_type == ObservationType.HP_PERCENT_DELTA.value:
            value = observed_value
        before = cls._decimal(payload.get("observed_hp_percent_before"), default=None)
        after = cls._decimal(payload.get("observed_hp_percent_after"), default=None)
        if value is None and before is not None and after is not None:
            return before - after
        return cls._decimal(value, default=None)

    @staticmethod
    def _panel_stat(panel: Any, stat_key: str) -> Decimal | None:
        if not isinstance(panel, dict):
            return None
        return EstimateService._decimal(panel.get(stat_key), default=None)

    @staticmethod
    def _decimal(value: Any, *, default: Decimal | None) -> Decimal | None:
        if value is None:
            return default
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return default

    @classmethod
    def _positive_int(cls, value: Any, *, default: int) -> int:
        parsed = cls._non_negative_int(value, default=default)
        if parsed is None or parsed <= 0:
            return default
        return parsed

    @staticmethod
    def _non_negative_int(value: Any, *, default: int | None) -> int | None:
        if value is None:
            return default
        try:
            parsed = int(value)
        except (ValueError, TypeError):
            return default
        return parsed if parsed >= 0 else default

    @staticmethod
    def _ceil_decimal(value: Decimal) -> int:
        return int(value.to_integral_value(rounding=ROUND_CEILING))

    @staticmethod
    def _floor_decimal(value: Decimal) -> int:
        return int(value.to_integral_value(rounding=ROUND_FLOOR))

    @classmethod
    def _extract_formula_context(
        cls,
        payload: dict[str, Any],
        inference_result: dict[str, Any],
    ) -> dict[str, Any]:
        keys = {
            "enemy_role",
            "formula_type",
            "skill_id",
            "skill_category",
            "skill_element_type",
            "base_power",
            "damage_tolerance",
            "percent_tolerance",
            "observed_damage_value",
            "observed_hp_percent_delta",
            "observed_order",
            "self_speed",
            "snapshot_id",
            "rule_resolution_enabled",
        }
        context = {key: payload.get(key) for key in keys if key in payload}
        if "rule_resolution_details" in payload:
            context["rule_resolution_details"] = payload.get("rule_resolution_details")
        context["modifier_summary"] = cls._build_modifier_summary(payload)
        context["key_multipliers"] = cls._build_key_multiplier_summary(payload)
        context["formula_inputs"] = cls._formula_input_summary(payload)
        context["estimate_summary"] = {
            "status": inference_result.get("status"),
            "inferred_stat_count": inference_result.get("inferred_stat_count"),
            "affected_stats": inference_result.get("affected_stats"),
        }
        return context

    @classmethod
    def _build_evidence_explanation(
        cls,
        evidence: EnemyPanelEstimateEvidence,
    ) -> dict[str, Any]:
        inferred_stats = loads_json(evidence.inferred_stats_json, {}) or {}
        constraint_delta = loads_json(evidence.constraint_delta_json, {}) or {}
        formula_context = loads_json(evidence.formula_context_json, {}) or {}
        unknown_factors = loads_json(evidence.unknown_factors_json, []) or []
        conflict = loads_json(evidence.conflict_json, None)
        affected_stats = constraint_delta.get("affected_stats", [])
        status = evidence.confidence or constraint_delta.get("status") or "recorded"
        formula_inputs = (
            formula_context.get("formula_inputs", {})
            if isinstance(formula_context, dict)
            else {}
        )
        modifier_summary = (
            formula_context.get("modifier_summary", {})
            if isinstance(formula_context, dict)
            else {}
        )
        key_multipliers = (
            formula_context.get("key_multipliers", {})
            if isinstance(formula_context, dict)
            else {}
        )
        constraint_effects = (
            constraint_delta.get("constraint_effects", [])
            if isinstance(constraint_delta, dict)
            else []
        )
        if inferred_stats:
            summary = "已根据本次观测生成属性约束。"
        elif unknown_factors:
            summary = "本次观测已记录，但仍有未知因素，暂不能形成完整属性约束。"
        else:
            summary = "本次观测已记录为实时估计证据。"
        if conflict:
            summary = "本次观测与已有约束存在冲突，需要人工复核。"
        return {
            "summary": summary,
            "status": status,
            "event": {
                "source_event_id": evidence.source_event_id,
                "snapshot_id": (
                    formula_context.get("snapshot_id")
                    if isinstance(formula_context, dict)
                    else None
                ),
            },
            "observation_type": evidence.observation_type,
            "affected_stats": affected_stats,
            "inferred_stat_keys": (
                list(inferred_stats.keys()) if isinstance(inferred_stats, dict) else []
            ),
            "formula": {
                "type": (
                    formula_context.get("formula_type")
                    if isinstance(formula_context, dict)
                    else None
                ),
                "skill_id": (
                    formula_context.get("skill_id")
                    if isinstance(formula_context, dict)
                    else None
                ),
                "skill_category": (
                    formula_context.get("skill_category")
                    if isinstance(formula_context, dict)
                    else None
                ),
                "observed_damage_value": (
                    formula_context.get("observed_damage_value")
                    if isinstance(formula_context, dict)
                    else None
                ),
                "observed_hp_percent_delta": (
                    formula_context.get("observed_hp_percent_delta")
                    if isinstance(formula_context, dict)
                    else None
                ),
                "present_inputs": formula_inputs.get("present", []),
                "missing_inputs": formula_inputs.get("missing", []),
                "key_multipliers": key_multipliers,
            },
            "constraint_changes": (
                constraint_effects if isinstance(constraint_effects, list) else []
            ),
            "modifiers": modifier_summary,
            "unknown_factors": [str(item) for item in unknown_factors],
            "why_no_constraint": cls._why_no_constraint(
                inferred_stats=inferred_stats,
                formula_inputs=formula_inputs,
                unknown_factors=unknown_factors,
            ),
            "conflict": conflict,
        }

    @staticmethod
    def _why_no_constraint(
        *,
        inferred_stats: dict[str, Any],
        formula_inputs: dict[str, Any],
        unknown_factors: list[Any],
    ) -> list[str]:
        if inferred_stats:
            return []
        reasons = [str(item) for item in unknown_factors]
        missing = formula_inputs.get("missing", []) if isinstance(formula_inputs, dict) else []
        if isinstance(missing, list):
            reasons.extend(f"missing_input:{item}" for item in missing)
        return list(dict.fromkeys(reasons))

    @classmethod
    def _build_key_multiplier_summary(cls, payload: dict[str, Any]) -> dict[str, Any]:
        factor = cls._attack_formula_factor(payload)
        reduction_items = cls._damage_reduction_summary(payload)
        return {
            "base_power": cls._string_decimal(payload.get("base_power")),
            "display_power": cls._string_decimal(payload.get("display_power")),
            "response_multiplier": cls._string_decimal(payload.get("response_multiplier"), "1"),
            "power_multiplier": cls._string_decimal(payload.get("power_multiplier"), "1"),
            "flat_power_bonus": cls._string_decimal(payload.get("flat_power_bonus"), "0"),
            "stat_stage_multiplier": cls._string_decimal(
                payload.get("stat_stage_multiplier"),
                "1",
            ),
            "stab_multiplier": cls._string_decimal(payload.get("stab_multiplier"), "1"),
            "type_multiplier": cls._string_decimal(payload.get("type_multiplier"), "1"),
            "weather_multiplier": cls._string_decimal(payload.get("weather_multiplier"), "1"),
            "unstable_multiplier": cls._string_decimal(payload.get("unstable_multiplier"), "1"),
            "damage_reductions": reduction_items,
            "formula_factor": (
                str(factor.quantize(Decimal("0.0001"))) if factor is not None else None
            ),
        }

    @classmethod
    def _damage_reduction_summary(cls, payload: dict[str, Any]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for index, item in enumerate(payload.get("damage_reductions", []) or []):
            reduction = cls._decimal(item, default=None)
            if reduction is None:
                result.append({"index": str(index), "value": str(item), "status": "invalid"})
            else:
                result.append(
                    {
                        "index": str(index),
                        "value": str(reduction),
                        "remaining_multiplier": str(Decimal("1") - reduction),
                    }
                )
        return result

    @classmethod
    def _string_decimal(cls, value: Any, default: str | None = None) -> str | None:
        fallback = Decimal(default) if default is not None else None
        decimal_value = cls._decimal(value, default=fallback)
        return str(decimal_value) if decimal_value is not None else None

    @classmethod
    def _build_modifier_summary(cls, payload: dict[str, Any]) -> dict[str, Any]:
        details = payload.get("rule_resolution_details")
        if not isinstance(details, dict):
            details = {}
        snapshot_summary = cls._snapshot_effect_summary(payload)
        damage_reductions = details.get("damage_reductions")
        stat_stage_multiplier = details.get("stat_stage_multiplier")
        weather = details.get("weather_multiplier")
        if weather is None and "weather_multiplier" in payload:
            weather = {
                "source": "payload_or_context",
                "value": str(payload.get("weather_multiplier")),
            }
        return {
            "rule_resolution_enabled": bool(payload.get("rule_resolution_enabled")),
            "weather": weather,
            "stat_stage_multiplier": stat_stage_multiplier,
            "damage_reductions": damage_reductions,
            "snapshot_effects": snapshot_summary,
            "unmapped_effect_modifier_count": cls._unmapped_snapshot_modifier_count(
                payload,
                details,
            ),
        }

    @classmethod
    def _formula_input_summary(cls, payload: dict[str, Any]) -> dict[str, list[str]]:
        required = [
            "skill_category",
            "base_power",
            "attacker_panel_stats",
            "defender_panel_stats",
            "observed_damage_value",
        ]
        present = [key for key in required if payload.get(key) is not None]
        missing = [key for key in required if payload.get(key) is None]
        return {"present": present, "missing": missing}

    @classmethod
    def _modifier_unknown_factors(cls, payload: dict[str, Any]) -> list[str]:
        unknowns: list[str] = []
        details = payload.get("rule_resolution_details")
        if not isinstance(details, dict):
            details = {}
        snapshot_summary = cls._snapshot_effect_summary(payload)
        if snapshot_summary["field_effect_count"] and not details.get("weather_multiplier"):
            unknowns.append("weather_modifier_rule_unmapped")
        if cls._unmapped_snapshot_modifier_count(payload, details):
            unknowns.append("active_effect_modifier_rules_unmapped")
        return unknowns

    @classmethod
    def _unmapped_snapshot_modifier_count(
        cls,
        payload: dict[str, Any],
        details: dict[str, Any],
    ) -> int:
        snapshot_payload = payload.get("snapshot_payload")
        if not isinstance(snapshot_payload, list):
            return 0
        mapped_effect_ids = cls._mapped_modifier_effect_ids(details)
        defender_side = payload.get("defender_side")
        defender_elf_id = payload.get("defender_elf_id")
        count = 0
        for item in snapshot_payload:
            if not isinstance(item, dict):
                continue
            effect_id = item.get("effect_id")
            if effect_id is not None and str(effect_id) in mapped_effect_ids:
                continue
            owner_scope = item.get("owner_scope")
            owner_side = item.get("owner_side")
            owner_elf_id = item.get("owner_elf_id")
            if owner_scope == "field":
                count += 1
            elif owner_scope in {"side", "elf"} and owner_side == defender_side:
                if (
                    owner_scope == "side"
                    or defender_elf_id is None
                    or owner_elf_id == defender_elf_id
                ):
                    count += 1
        return count

    @staticmethod
    def _mapped_modifier_effect_ids(details: dict[str, Any]) -> set[str]:
        mapped: set[str] = set()
        weather = details.get("weather_multiplier")
        if isinstance(weather, dict) and weather.get("effect_id") is not None:
            mapped.add(str(weather["effect_id"]))
        stat_stage = details.get("stat_stage_multiplier")
        if isinstance(stat_stage, dict) and isinstance(stat_stage.get("items"), list):
            for item in stat_stage["items"]:
                if isinstance(item, dict) and item.get("effect_id") is not None:
                    mapped.add(str(item["effect_id"]))
        reductions = details.get("damage_reductions")
        if isinstance(reductions, dict) and isinstance(reductions.get("items"), list):
            for item in reductions["items"]:
                if (
                    isinstance(item, dict)
                    and item.get("source_type") == "effect_snapshot"
                    and item.get("source_id") is not None
                ):
                    mapped.add(str(item["source_id"]))
        return mapped

    @staticmethod
    def _snapshot_effect_summary(payload: dict[str, Any]) -> dict[str, Any]:
        snapshot_payload = payload.get("snapshot_payload")
        if not isinstance(snapshot_payload, list):
            return {
                "active_effect_count": 0,
                "field_effect_count": 0,
                "defender_effect_count": 0,
                "effect_ids": [],
            }
        defender_side = payload.get("defender_side")
        defender_elf_id = payload.get("defender_elf_id")
        effect_ids: list[str] = []
        field_effect_count = 0
        defender_effect_count = 0
        for item in snapshot_payload:
            if not isinstance(item, dict):
                continue
            effect_id = item.get("effect_id")
            if effect_id is not None:
                effect_ids.append(str(effect_id))
            owner_scope = item.get("owner_scope")
            owner_side = item.get("owner_side")
            owner_elf_id = item.get("owner_elf_id")
            if owner_scope == "field":
                field_effect_count += 1
            elif owner_scope in {"side", "elf"} and owner_side == defender_side:
                if (
                    owner_scope == "side"
                    or defender_elf_id is None
                    or owner_elf_id == defender_elf_id
                ):
                    defender_effect_count += 1
        return {
            "active_effect_count": len(
                [item for item in snapshot_payload if isinstance(item, dict)]
            ),
            "field_effect_count": field_effect_count,
            "defender_effect_count": defender_effect_count,
            "effect_ids": effect_ids[:8],
        }

    @staticmethod
    def _append_unique_items(items: list[Any], new_items: list[Any]) -> list[Any]:
        result = [str(item) for item in items]
        for item in new_items:
            text = str(item)
            if text not in result:
                result.append(text)
        return result

    def _repair_default_config_if_needed(
        self,
        estimate: EnemyPanelEstimate,
        *,
        stat_constraints: dict[str, Any],
        inferred_stats: dict[str, Any],
    ) -> None:
        """明确推导出主属性时，若默认展示配置失效，则回填一组启发式配置。"""
        if not self._has_numeric_stat_constraints(stat_constraints):
            return

        current_panel = loads_json(estimate.default_panel_json, None)
        if isinstance(current_panel, dict):
            violations = self._panel_constraint_violations(current_panel, stat_constraints)
            if not violations:
                return

        if self._has_constraint_conflict(stat_constraints):
            existing_unknowns = loads_json(estimate.unknown_factors_json, []) or []
            estimate.unknown_factors_json = dumps_json(
                self._append_unique_items(
                    existing_unknowns,
                    ["当前推导约束存在冲突，暂不自动改写默认展示配置"],
                )
            )
            return

        preferred_stat = self._preferred_repair_stat(inferred_stats)
        replacement = (
            self._build_repair_default_config(estimate.elf_id, preferred_stat)
            if preferred_stat is not None
            else self._build_auto_default_config(estimate.elf_id)
        )
        if replacement is None:
            existing_unknowns = loads_json(estimate.unknown_factors_json, []) or []
            estimate.unknown_factors_json = dumps_json(
                self._append_unique_items(
                    existing_unknowns,
                    ["当前推导主属性缺少可用性格规则，暂不自动改写默认展示配置"],
                )
            )
            return

        default_config, panel = replacement
        default_config = {
            **default_config,
            "preset": "auto_repaired_by_realtime_constraints",
            "repair": {
                **dict(default_config.get("repair") or {}),
                "reason": "previous_default_config_violated_realtime_constraints",
                "preferred_stat": preferred_stat,
                "fallback": "base_stat_heuristic" if preferred_stat is None else "derived_stat",
            },
        }
        panel = {**panel, "source": "realtime_constraint_repair"}
        violations = self._panel_constraint_violations(panel, stat_constraints)
        if violations:
            existing_unknowns = loads_json(estimate.unknown_factors_json, []) or []
            estimate.unknown_factors_json = dumps_json(
                self._append_unique_items(
                    existing_unknowns,
                    ["自动回填配置仍不满足当前推导约束，保留玩家原默认配置等待手动选择"],
                )
            )
            return

        estimate.default_config_json = dumps_json(default_config)
        estimate.default_panel_json = dumps_json(panel)
        estimate.estimated_panel_json = dumps_json(panel)
        existing_unknowns = loads_json(estimate.unknown_factors_json, []) or []
        estimate.unknown_factors_json = dumps_json(
            self._append_unique_items(
                existing_unknowns,
                ["默认展示配置已按当前实时推导约束自动回填"],
            )
        )

    def _build_repair_default_config(
        self,
        elf_id: str,
        preferred_stat: str,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        elf = self.db.get(ElfDefinition, elf_id)
        if elf is None or elf.deleted_at is not None:
            return None

        dominant_attack = (
            StatKey.PHYSICAL_ATTACK
            if elf.base_physical_attack_talent >= elf.base_magic_attack_talent
            else StatKey.MAGIC_ATTACK
        )
        positive_stat = StatKey(preferred_stat)
        if positive_stat == StatKey.PHYSICAL_ATTACK:
            negative_stat = StatKey.MAGIC_ATTACK
        elif positive_stat == StatKey.MAGIC_ATTACK:
            negative_stat = StatKey.PHYSICAL_ATTACK
        elif positive_stat == StatKey.SPEED:
            negative_stat = (
                StatKey.MAGIC_ATTACK
                if dominant_attack == StatKey.PHYSICAL_ATTACK
                else StatKey.PHYSICAL_ATTACK
            )
        else:
            return None

        nature = self.db.scalars(
            select(NatureDefinition).where(
                NatureDefinition.positive_stat == positive_stat.value,
                NatureDefinition.negative_stat == negative_stat.value,
                NatureDefinition.deleted_at.is_(None),
            )
        ).first()
        if nature is None:
            return None

        talents = {stat.value: 0 for stat in StatKey}
        talents[StatKey.HP.value] = 10
        talents[StatKey.SPEED.value] = 10
        talents[positive_stat.value] = 10
        if positive_stat == StatKey.SPEED:
            talents[dominant_attack.value] = 10

        individual = IndividualTalentDistribution(**talents)
        panel = StatCalculator.calculate_panel_stats(
            base=self._elf_to_base_talent_block(elf),
            individual=individual,
            nature=self._nature_to_rule(nature),
        )
        return (
            {
                "preset": "auto_repaired_by_realtime_constraints",
                "nature_id": nature.nature_id,
                "individual_talent_distribution": individual.model_dump(),
                "repair": {
                    "reason": "previous_default_config_violated_realtime_constraints",
                    "preferred_stat": preferred_stat,
                },
            },
            {**panel.model_dump(), "source": "realtime_constraint_repair"},
        )

    @staticmethod
    def _preferred_repair_stat(inferred_stats: dict[str, Any]) -> str | None:
        for stat_key in (
            StatKey.PHYSICAL_ATTACK.value,
            StatKey.MAGIC_ATTACK.value,
            StatKey.SPEED.value,
        ):
            if stat_key in inferred_stats:
                return stat_key
        return None

    @classmethod
    def _has_numeric_stat_constraints(cls, stat_constraints: dict[str, Any]) -> bool:
        if not isinstance(stat_constraints, dict):
            return False
        for stat in StatKey:
            entry = stat_constraints.get(stat.value)
            if not isinstance(entry, dict):
                continue
            if (
                cls._non_negative_int(entry.get("integer_min"), default=None) is not None
                and cls._non_negative_int(entry.get("integer_max"), default=None) is not None
            ):
                return True
        return False

    @staticmethod
    def _has_constraint_conflict(stat_constraints: dict[str, Any]) -> bool:
        if not isinstance(stat_constraints, dict):
            return False
        return any(
            isinstance(stat_constraints.get(stat.value), dict)
            and stat_constraints[stat.value].get("status") == "constraint_conflict"
            for stat in StatKey
        )

    @classmethod
    def _panel_constraint_violations(
        cls,
        panel: dict[str, Any],
        stat_constraints: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """检查一个展示面板是否满足当前整数推导约束。"""
        violations: list[dict[str, Any]] = []
        for stat in StatKey:
            entry = stat_constraints.get(stat.value)
            if not isinstance(entry, dict):
                continue
            integer_min = cls._non_negative_int(entry.get("integer_min"), default=None)
            integer_max = cls._non_negative_int(entry.get("integer_max"), default=None)
            actual = cls._non_negative_int(panel.get(stat.value), default=None)
            if integer_min is None or integer_max is None or actual is None:
                continue
            if actual < integer_min or actual > integer_max:
                violations.append(
                    {
                        "stat_key": stat.value,
                        "expected_min": integer_min,
                        "expected_max": integer_max,
                        "actual": actual,
                    }
                )
        return violations
