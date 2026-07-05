"""
伤害事件服务。

第一阶段只负责事实记录、快照绑定和公式占位返回。伤害观测会同步写入
敌方实时面板估计。
"""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext, PanelStats
from app.calculation.rule_resolver import RuleResolver
from app.core.enums import BattleEventType, DamageDisplayType, EventSource
from app.inference.observation_event import ObservationEventInput
from app.inference.observation_types import ObservationType
from app.models.battle import Battle, BattleElfState
from app.models.event import BattleEvent, DamageEvent, ResourceChangeEvent
from app.models.static import EffectDefinition, SkillDefinition
from app.schemas.event import DamageEventCreate, DamageEventCreateResult
from app.services.battle_service import BattleService
from app.services.effect_operation_executor import EffectOperationExecutor
from app.services.estimate_service import EstimateService
from app.services.snapshot_service import SnapshotService
from app.services.turn_settlement_service import TurnSettlementService
from app.utils.json import dumps_json, loads_json


class DamageEventService:
    """伤害事件业务服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_damage_event(
        self,
        battle_id: str,
        payload: DamageEventCreate,
    ) -> DamageEventCreateResult:
        """
        创建伤害事件、状态快照并更新实时面板估计。

        处理顺序：
        1. 创建 BattleEvent；
        2. 创建事件发生瞬间的 BattleEffectSnapshot；
        3. 创建 DamageEvent；
        4. 构造 DamageFormulaContext；
        5. 调用伤害计算器，返回公式计算结果或占位状态；
        6. 可选更新防御方生命百分比。
        """
        battle_service = BattleService(self.db)
        battle = battle_service.require_battle(battle_id)
        turn_number = payload.turn_number if payload.turn_number is not None else battle.turn_number
        total_damage = self._resolve_total_damage(payload)
        hp_percent_delta = self._resolve_hp_percent_delta(payload)
        effective_payload = payload.model_dump(mode="json")
        status_rule = self._resolve_status_effect_rule(payload.effect_id)
        formula_type = payload.formula_type or "attack"
        effect_layers = payload.effect_layers or self._resolve_active_effect_layers(
            battle_id=battle_id,
            effect_id=payload.effect_id,
            target_side=payload.defender_side,
            target_elf_id=payload.defender_elf_id,
        )
        skill_element_type = payload.skill_element_type or self._status_rule_element_type(
            status_rule
        )
        effective_payload["formula_type"] = formula_type
        effective_payload["turn_number"] = turn_number
        if total_damage is not None:
            effective_payload["damage_dealt"] = total_damage
            effective_payload["computed_total_damage_value"] = total_damage
        if payload.effect_id:
            effective_payload["effect_id"] = payload.effect_id
        if effect_layers is not None:
            effective_payload["effect_layers"] = effect_layers
        if skill_element_type is not None:
            effective_payload["skill_element_type"] = skill_element_type
        status_percent_per_layer = self._status_rule_percent_per_layer(status_rule)
        if status_percent_per_layer is not None:
            effective_payload["status_percent_per_layer"] = float(status_percent_per_layer)
        status_uses_type_effectiveness = self._status_rule_uses_type_effectiveness(status_rule)
        if status_uses_type_effectiveness is not None:
            effective_payload["status_uses_type_effectiveness"] = status_uses_type_effectiveness
        defense_context = self._resolve_defense_response_context(
            battle_id=battle_id,
            turn_number=turn_number,
            defender_side=payload.defender_side,
            defender_elf_id=payload.defender_elf_id,
            explicit_defense_skill_id=payload.defense_skill_id,
            explicit_response_flags={
                "response_attack_success": payload.response_attack_success,
                "response_defense_success": payload.response_defense_success,
                "response_status_success": payload.response_status_success,
            },
        )
        effective_payload.update(defense_context)
        condition_flags = self._resolve_condition_flags(
            battle_id=battle_id,
            turn_number=turn_number,
            payload=payload,
        )
        if condition_flags:
            effective_payload["condition_flags"] = condition_flags
            for key, value in condition_flags.items():
                effective_payload.setdefault(key, value)
        rule_payload = dict(effective_payload)
        if self._should_resolve_rules(rule_payload):
            rule_payload["resolve_rules"] = True

        battle_event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=turn_number,
            event_type=self._event_type_for(payload.damage_display_type),
            actor_side=payload.attacker_side,
            actor_elf_id=payload.attacker_elf_id,
            target_side=payload.defender_side,
            target_elf_id=payload.defender_elf_id,
            skill_id=payload.skill_id,
            skill_confirmed=payload.skill_confirmed,
            source=EventSource.MANUAL_INPUT.value,
            manual_override=True,
            payload_json=dumps_json(effective_payload),
            notes=payload.notes,
        )
        self.db.add(battle_event)
        self.db.flush()
        observed_skill_slot = battle_service.ensure_observed_skill_slot(battle_event)
        if observed_skill_slot:
            effective_payload["skill_runtime"] = observed_skill_slot
            battle_event.payload_json = dumps_json(effective_payload)

        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle_id=battle_id,
            turn_number=turn_number,
            source_event_id=battle_event.event_id,
            commit=False,
        )
        battle_event.snapshot_id = snapshot.snapshot_id

        damage_event = DamageEvent(
            event_id=f"damage_event_{uuid4().hex}",
            battle_id=battle_id,
            battle_event_id=battle_event.event_id,
            attacker_side=payload.attacker_side,
            attacker_elf_id=payload.attacker_elf_id,
            defender_side=payload.defender_side,
            defender_elf_id=payload.defender_elf_id,
            skill_id=payload.skill_id,
            damage_display_type=payload.damage_display_type.value,
            damage_value=total_damage,
            final_total_damage_value=payload.final_total_damage_value,
            per_hit_damage_value=payload.per_hit_damage_value,
            hit_count=payload.hit_count,
            computed_total_damage_value=self._computed_combo_total(payload),
            combo_count_source=payload.combo_count_source,
            combo_confidence=payload.combo_confidence,
            hp_percent_before=payload.hp_percent_before,
            hp_percent_after=payload.hp_percent_after,
            hp_percent_delta=hp_percent_delta,
            enemy_hp_percent_damage=payload.enemy_hp_percent_damage or hp_percent_delta,
            calculation_confidence=0.0,
            manual_override=True,
        )
        self.db.add(damage_event)
        self.db.flush()

        attacker_state = self._get_elf_state(
            battle_id=battle_id,
            side=payload.attacker_side,
            elf_id=payload.attacker_elf_id,
        )
        defender_state = self._get_elf_state(
            battle_id=battle_id,
            side=payload.defender_side,
            elf_id=payload.defender_elf_id,
        )
        defender_panel_stats = self._panel_stats_from_state(defender_state)

        context = DamageFormulaContext(
            battle_id=battle_id,
            damage_event_id=damage_event.event_id,
            battle_event_id=battle_event.event_id,
            snapshot_id=snapshot.snapshot_id,
            formula_type=formula_type,
            attacker_side=payload.attacker_side,
            attacker_elf_id=payload.attacker_elf_id,
            defender_side=payload.defender_side,
            defender_elf_id=payload.defender_elf_id,
            skill_id=payload.skill_id,
            defense_skill_id=effective_payload.get("defense_skill_id"),
            response_attack_success=effective_payload.get("response_attack_success"),
            response_defense_success=effective_payload.get("response_defense_success"),
            response_status_success=effective_payload.get("response_status_success"),
            skill_element_type=skill_element_type,
            attacker_panel_stats=self._panel_stats_from_state(attacker_state),
            defender_panel_stats=defender_panel_stats,
            defender_max_hp=defender_panel_stats.hp if defender_panel_stats is not None else None,
            damage_display_type=payload.damage_display_type.value,
            effect_id=payload.effect_id,
            effect_layers=effect_layers or 1,
            status_percent_per_layer=status_percent_per_layer,
            status_uses_type_effectiveness=status_uses_type_effectiveness,
            observed_damage_value=total_damage,
            observed_hp_percent_delta=hp_percent_delta,
            snapshot_payload=loads_json(snapshot.full_snapshot_json, []),
            notes=payload.notes,
        )
        context = RuleResolver(self.db).resolve_damage_context(context, rule_payload)
        skill_modifier = {"items": []}
        if formula_type == "attack" and payload.skill_id:
            slot_id = (
                observed_skill_slot.get("slot_id")
                if isinstance(observed_skill_slot, dict)
                else None
            )
            skill_modifier = battle_service._skill_power_modifier_from_effects(
                context,
                loads_json(snapshot.full_snapshot_json, []),
                str(slot_id or ""),
            )
            context.power_multiplier = (
                Decimal(str(context.power_multiplier)) * skill_modifier["multiplier"]
            )
            context.flat_power_bonus = (
                Decimal(str(context.flat_power_bonus)) + skill_modifier["flat_power_bonus"]
            )
            hit_rule_detail = context.rule_resolution_details.get("hit_rule", {})
            hit_rule_source = (
                hit_rule_detail.get("source")
                if isinstance(hit_rule_detail, dict)
                else None
            )
            if hit_rule_source not in {"manual_payload", "auto_effect_prefill"}:
                context.hit_count = max(
                    int(
                        Decimal(
                            str(
                                int(context.hit_count or 1)
                                + int(skill_modifier["hit_count_delta"])
                            )
                        )
                        * Decimal(
                            str(skill_modifier.get("hit_count_multiplier") or "1")
                        )
                    ),
                    1,
                )
            if skill_modifier["items"]:
                context.rule_resolution_details["skill_modifier"] = skill_modifier["items"]
        damage_event.formula_context_json = dumps_json(context)
        damage_result = DamageCalculator().calculate(context)
        damage_event.calculation_confidence = damage_result.confidence
        consumed_skill_modifiers = battle_service.consume_skill_modifier_effect_uses(
            battle_event,
            skill_modifier["items"],
            reason="damage_event_skill_modifier_consumed",
        )
        if consumed_skill_modifiers:
            effective_payload["consumed_skill_modifier_effects"] = consumed_skill_modifiers
            battle_event.payload_json = dumps_json(effective_payload)
        damage_skill_runtime_result = self._process_damage_skill_runtime_if_needed(
            battle_service,
            battle_event,
        )
        if damage_skill_runtime_result:
            if (
                isinstance(observed_skill_slot, dict)
                and observed_skill_slot.get("slot_created") is True
            ):
                damage_skill_runtime_result["slot_created"] = True
            effective_payload["skill_runtime"] = damage_skill_runtime_result
            battle_event.payload_json = dumps_json(effective_payload)
        estimate_observation_results = self._process_estimate_observations(
            damage_event=damage_event,
            payload=payload,
            context=context,
            total_damage=total_damage,
            hp_percent_delta=hp_percent_delta,
        )
        inference_result = {
            "status": damage_result.status,
            "damage_event_id": damage_event.event_id,
            "estimate_updated": bool(estimate_observation_results),
            "confidence": damage_result.confidence,
            "missing_parts": damage_result.missing_parts,
            "message": damage_result.message,
        }
        if estimate_observation_results:
            inference_result = {
                **inference_result,
                "estimate_observation_results": estimate_observation_results,
            }
        self._create_resource_change_for_damage(
            battle_id=battle_id,
            battle_event_id=battle_event.event_id,
            payload=payload,
            total_damage=total_damage,
            hp_percent_delta=hp_percent_delta,
        )
        self._update_defender_hp_state(battle, payload, total_damage)
        damage_taken_runtime_listener_results = battle_service.apply_damage_taken_runtime_listeners(
            battle_event=battle_event,
            defender_side=payload.defender_side,
            defender_elf_id=payload.defender_elf_id,
            damage_value=total_damage,
        )
        if damage_taken_runtime_listener_results:
            effective_payload["damage_taken_runtime_listener_results"] = (
                damage_taken_runtime_listener_results
            )
            battle_event.payload_json = dumps_json(effective_payload)
        post_damage_operation_results = EffectOperationExecutor(self.db).execute_for_damage_event(
            battle_event
        )
        if post_damage_operation_results:
            effective_payload["post_damage_effect_operation_results"] = (
                post_damage_operation_results
            )
            battle_event.payload_json = dumps_json(effective_payload)
        post_settlement_events = TurnSettlementService(self.db).settle_post_attack(
            battle=battle,
            turn_number=turn_number,
            trigger_battle_event_id=battle_event.event_id,
            attacker_side=payload.attacker_side,
            attacker_elf_id=payload.attacker_elf_id,
            defender_side=payload.defender_side,
            defender_elf_id=payload.defender_elf_id,
            trigger_skill_id=payload.skill_id,
        )

        self.db.commit()
        self.db.refresh(battle_event)
        self.db.refresh(damage_event)
        return DamageEventCreateResult(
            battle_event=battle_event,
            damage_event=damage_event,
            snapshot_id=snapshot.snapshot_id,
            inference_result=inference_result,
            post_settlement_events=post_settlement_events,
        )

    def _process_damage_skill_runtime_if_needed(
        self,
        battle_service: BattleService,
        battle_event: BattleEvent,
    ) -> dict | None:
        """
        伤害事件也代表一次攻击技能使用。

        公式计算必须基于事件发生瞬间的快照，因此这里放在本次伤害结算之后再处理
        技能槽扣能、使用后威力/能耗钩子、以及“使用其他同系技能”监听，确保只影响
        后续面板预览，不污染本次伤害计算。
        """
        if battle_event.skill_id is None or not battle_event.skill_confirmed:
            return None
        if self._same_turn_skill_use_event_exists(battle_event):
            return None
        result = battle_service._process_skill_runtime(battle_event)
        if isinstance(result, dict):
            result.setdefault("record_source", "damage_event")
        return result

    def _same_turn_skill_use_event_exists(self, battle_event: BattleEvent) -> bool:
        """若同回合已记录对应 skill_use，则避免伤害事件重复触发技能运行时钩子。"""
        if (
            battle_event.skill_id is None
            or battle_event.actor_side is None
            or battle_event.actor_elf_id is None
        ):
            return False
        existing = self.db.scalars(
            select(BattleEvent).where(
                BattleEvent.battle_id == battle_event.battle_id,
                BattleEvent.turn_number == battle_event.turn_number,
                BattleEvent.event_type == BattleEventType.SKILL_USE.value,
                BattleEvent.actor_side == battle_event.actor_side,
                BattleEvent.actor_elf_id == battle_event.actor_elf_id,
                BattleEvent.skill_id == battle_event.skill_id,
                BattleEvent.is_voided.is_(False),
            )
        ).first()
        return existing is not None

    @staticmethod
    def _resolve_total_damage(payload: DamageEventCreate) -> int | None:
        """根据伤害显示类型得出总伤害。"""
        if payload.damage_display_type == DamageDisplayType.SINGLE_DAMAGE:
            return payload.damage_value
        if payload.damage_display_type == DamageDisplayType.VISUAL_TOTAL_DAMAGE:
            return payload.final_total_damage_value
        if payload.damage_display_type == DamageDisplayType.COMBO_REPEATED_DAMAGE:
            return DamageEventService._computed_combo_total(payload)
        return payload.damage_value

    @staticmethod
    def _computed_combo_total(payload: DamageEventCreate) -> int | None:
        """连击伤害由单段伤害 × 次数计算得出。"""
        if payload.damage_display_type != DamageDisplayType.COMBO_REPEATED_DAMAGE:
            return None
        if payload.per_hit_damage_value is None or payload.hit_count is None:
            return None
        return payload.per_hit_damage_value * payload.hit_count

    @staticmethod
    def _resolve_hp_percent_delta(payload: DamageEventCreate) -> float | None:
        """根据前后生命百分比计算扣血百分比。"""
        if payload.hp_percent_before is None or payload.hp_percent_after is None:
            return payload.enemy_hp_percent_damage
        return round(payload.hp_percent_before - payload.hp_percent_after, 4)

    def _resolve_status_effect_rule(self, effect_id: str | None) -> dict:
        """读取状态结算规则，用于手动录入状态伤害时补全属性和百分比。"""
        if not effect_id:
            return {}
        definition = self.db.get(EffectDefinition, effect_id)
        if definition is None or definition.deleted_at is not None:
            return {}
        resource_rule = loads_json(definition.resource_modifier_json, {})
        return resource_rule if isinstance(resource_rule, dict) else {}

    def _resolve_active_effect_layers(
        self,
        *,
        battle_id: str,
        effect_id: str | None,
        target_side: str | None,
        target_elf_id: str | None,
    ) -> int | None:
        """未手动指定层数时，从目标身上或目标队伍侧当前生效状态读取层数。"""
        if not effect_id or not target_side:
            return None
        from app.models.effect import BattleEffectInstance

        base_conditions = [
            BattleEffectInstance.battle_id == battle_id,
            BattleEffectInstance.effect_id == effect_id,
            BattleEffectInstance.is_active.is_(True),
            BattleEffectInstance.owner_side == target_side,
        ]
        if target_elf_id:
            elf_instance = self.db.scalars(
                select(BattleEffectInstance)
                .where(
                    *base_conditions,
                    BattleEffectInstance.owner_scope == "elf",
                    BattleEffectInstance.owner_elf_id == target_elf_id,
                )
                .order_by(BattleEffectInstance.created_at.desc())
            ).first()
            side_instance = self.db.scalars(
                select(BattleEffectInstance)
                .where(*base_conditions, BattleEffectInstance.owner_scope == "side")
                .order_by(BattleEffectInstance.created_at.desc())
            ).first()
            instance = elf_instance or side_instance
        else:
            instance = self.db.scalars(
                select(BattleEffectInstance)
                .where(*base_conditions)
                .order_by(BattleEffectInstance.created_at.desc())
            ).first()
        return int(instance.layers) if instance is not None and instance.layers else None

    @staticmethod
    def _status_rule_element_type(resource_rule: dict) -> str | None:
        value = resource_rule.get("element_type")
        return str(value) if value is not None and str(value) else None

    @staticmethod
    def _status_rule_percent_per_layer(resource_rule: dict) -> Decimal | None:
        value = resource_rule.get("percent_per_layer")
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    @staticmethod
    def _status_rule_uses_type_effectiveness(resource_rule: dict) -> bool | None:
        value = resource_rule.get("uses_type_effectiveness")
        return bool(value) if value is not None else None

    @staticmethod
    def _resolve_value_damage_delta(payload: DamageEventCreate) -> int | None:
        """根据前后精确生命值计算伤害值。"""
        if payload.hp_value_before is None or payload.hp_value_after is None:
            return None
        return max(payload.hp_value_before - payload.hp_value_after, 0)

    @staticmethod
    def _event_type_for(display_type: DamageDisplayType) -> str:
        """根据显示类型选择通用事件类型。"""
        if display_type == DamageDisplayType.COMBO_REPEATED_DAMAGE:
            return BattleEventType.COMBO_DAMAGE.value
        return BattleEventType.DAMAGE.value

    @staticmethod
    def _should_resolve_rules(payload: dict) -> bool:
        """有技能或应对/防御上下文时启用规则解析，结果只进入实时估计上下文。"""
        if payload.get("formula_type") not in {None, "attack"}:
            return True
        return any(
            payload.get(key) is not None
            for key in (
                "effect_id",
                "skill_element_type",
                "skill_id",
                "defense_skill_id",
                "response_attack_success",
                "response_defense_success",
                "response_status_success",
                "condition_flags",
            )
        )

    def _resolve_condition_flags(
        self,
        *,
        battle_id: str,
        turn_number: int,
        payload: DamageEventCreate,
    ) -> dict[str, bool]:
        """合并手动条件和同回合可推断条件，供技能分支读取。"""
        result: dict[str, bool] = {}
        if isinstance(payload.condition_flags, dict):
            result.update(
                {
                    str(key): bool(value)
                    for key, value in payload.condition_flags.items()
                    if isinstance(key, str) and isinstance(value, bool)
                }
            )

        switched_sides = self._switched_sides_this_turn(
            battle_id=battle_id,
            turn_number=turn_number,
        )
        if "self" in switched_sides:
            result.setdefault("self_switched_this_turn", True)
        if "enemy" in switched_sides:
            result.setdefault("enemy_switched_this_turn", True)
        if payload.defender_side in switched_sides:
            result.setdefault("target_switched_this_turn", True)
            result.setdefault("defender_switched_this_turn", True)
        if payload.attacker_side in switched_sides:
            result.setdefault("actor_switched_this_turn", True)
        return result

    def _switched_sides_this_turn(self, *, battle_id: str, turn_number: int) -> set[str]:
        stmt = select(BattleEvent.actor_side).where(
            BattleEvent.battle_id == battle_id,
            BattleEvent.turn_number == turn_number,
            BattleEvent.event_type == BattleEventType.SWITCH_ELF.value,
            BattleEvent.actor_side.is_not(None),
            BattleEvent.is_voided.is_(False),
        )
        return {side for side in self.db.scalars(stmt).all() if side}

    def _resolve_defense_response_context(
        self,
        *,
        battle_id: str,
        turn_number: int,
        defender_side: str | None,
        defender_elf_id: str | None,
        explicit_defense_skill_id: str | None,
        explicit_response_flags: dict[str, bool | None],
    ) -> dict:
        """从同回合已记录的防御动作推导本次伤害的防御/应对上下文。"""
        result: dict = {
            key: value for key, value in explicit_response_flags.items() if value is not None
        }
        if explicit_defense_skill_id:
            result["defense_skill_id"] = explicit_defense_skill_id
            result["defense_response_source"] = "manual_damage_payload"
            return result
        if defender_side is None or defender_elf_id is None:
            return result

        defense_event = self._find_latest_unconsumed_defense_event(
            battle_id=battle_id,
            turn_number=turn_number,
            defender_side=defender_side,
            defender_elf_id=defender_elf_id,
        )
        if defense_event is None or defense_event.skill_id is None:
            return result

        result.update(
            self._infer_response_flags_from_defense_skill(
                defense_event.skill_id,
                existing_flags=result,
            )
        )
        result.update(
            {
                "defense_skill_id": defense_event.skill_id,
                "defense_response_source": "latest_same_turn_defense_skill_event",
                "defense_response_event_id": defense_event.event_id,
                "defense_response_action_order": defense_event.action_order,
            }
        )
        return result

    def _find_latest_unconsumed_defense_event(
        self,
        *,
        battle_id: str,
        turn_number: int,
        defender_side: str,
        defender_elf_id: str,
    ) -> BattleEvent | None:
        """查找同回合该防御方最近一次尚未被自动消费的防御技能事件。"""
        stmt = (
            select(BattleEvent)
            .where(
                BattleEvent.battle_id == battle_id,
                BattleEvent.turn_number == turn_number,
                BattleEvent.event_type == BattleEventType.SKILL_USE.value,
                BattleEvent.actor_side == defender_side,
                BattleEvent.actor_elf_id == defender_elf_id,
                BattleEvent.skill_id.is_not(None),
                BattleEvent.is_voided.is_(False),
            )
            .order_by(
                BattleEvent.action_order.desc().nullslast(),
                BattleEvent.created_at.desc(),
            )
        )
        for event in self.db.scalars(stmt).all():
            if not self._skill_has_defense_modifier(event.skill_id):
                continue
            if self._defense_event_already_consumed(
                battle_id=battle_id,
                turn_number=turn_number,
                defense_event=event,
                defender_side=defender_side,
                defender_elf_id=defender_elf_id,
            ):
                continue
            return event
        return None

    def _defense_event_already_consumed(
        self,
        *,
        battle_id: str,
        turn_number: int,
        defense_event: BattleEvent,
        defender_side: str,
        defender_elf_id: str,
    ) -> bool:
        """防御动作默认只自动套到下一次命中的伤害事件。"""
        stmt = select(BattleEvent).where(
            BattleEvent.battle_id == battle_id,
            BattleEvent.turn_number == turn_number,
            BattleEvent.target_side == defender_side,
            BattleEvent.target_elf_id == defender_elf_id,
            BattleEvent.event_type.in_(
                [BattleEventType.DAMAGE.value, BattleEventType.COMBO_DAMAGE.value]
            ),
            BattleEvent.is_voided.is_(False),
        )
        for event in self.db.scalars(stmt).all():
            payload = loads_json(event.payload_json, {})
            if isinstance(payload, dict) and (
                payload.get("defense_response_event_id") == defense_event.event_id
            ):
                return True
        return False

    def _skill_has_defense_modifier(self, skill_id: str | None) -> bool:
        """判断技能定义是否包含可用于伤害减免的防御规则。"""
        if skill_id is None:
            return False
        skill = self.db.get(SkillDefinition, skill_id)
        if skill is None or skill.deleted_at is not None:
            return False
        rule = loads_json(skill.damage_rule_json, {})
        if not isinstance(rule, dict):
            return False
        return any(
            rule.get(key) is not None
            for key in ("damage_reduction", "reduction", "damage_multiplier", "multiplier")
        )

    def _infer_response_flags_from_defense_skill(
        self,
        skill_id: str,
        *,
        existing_flags: dict,
    ) -> dict[str, bool]:
        """按防御技能 response_rule 推导本次攻击伤害的应对旗标。"""
        explicit_flags = {
            key: bool(value)
            for key, value in existing_flags.items()
            if key.startswith("response_") and value is not None
        }
        if explicit_flags:
            return explicit_flags

        skill = self.db.get(SkillDefinition, skill_id)
        if skill is None or skill.deleted_at is not None:
            return {}
        rule = loads_json(skill.damage_rule_json, {})
        response_rule = rule.get("response_rule") if isinstance(rule, dict) else None
        if not isinstance(response_rule, dict):
            return {}

        condition = response_rule.get("condition")
        target = response_rule.get("target") or response_rule.get("response_target")
        if condition is None and target in {"attack", "defense", "status"}:
            condition = f"response_{target}_success"

        # DamageEvent 表示一次攻击伤害，因此 target=attack 的防御应对可以自动判定成功。
        if condition == "response_attack_success":
            return {"response_attack_success": True}
        if isinstance(condition, str) and condition.startswith("response_"):
            return {condition: False}
        return {}

    def _get_elf_state(
        self,
        *,
        battle_id: str,
        side: str | None,
        elf_id: str | None,
    ) -> BattleElfState | None:
        """读取本场战斗中指定精灵的运行时状态。"""
        if side is None or elf_id is None:
            return None
        return self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == battle_id,
                BattleElfState.side == side,
                BattleElfState.elf_id == elf_id,
            )
        ).first()

    @staticmethod
    def _panel_stats_from_state(state: BattleElfState | None) -> PanelStats | None:
        """从运行时精灵状态解析伤害公式需要的六维面板。"""
        if state is None:
            return None
        stats = loads_json(state.panel_stats_json, {})
        if not isinstance(stats, dict):
            return None
        required = (
            "hp",
            "physical_attack",
            "physical_defense",
            "magic_attack",
            "magic_defense",
            "speed",
        )
        if any(stats.get(key) is None for key in required):
            return None
        return PanelStats(
            hp=int(stats["hp"]),
            physical_attack=int(stats["physical_attack"]),
            physical_defense=int(stats["physical_defense"]),
            magic_attack=int(stats["magic_attack"]),
            magic_defense=int(stats["magic_defense"]),
            speed=int(stats["speed"]),
        )

    def _create_resource_change_for_damage(
        self,
        *,
        battle_id: str,
        battle_event_id: str,
        payload: DamageEventCreate,
        total_damage: int | None,
        hp_percent_delta: float | None,
    ) -> None:
        """
        为伤害事件补充 ResourceChangeEvent。

        文档要求生命 / 能量变化需要进入事件日志。伤害详情仍由 DamageEvent 保存，
        这里额外记录一次 hp 资源变化，方便时间线、回放和后续纠错统一处理。
        """
        if payload.defender_side is None or payload.defender_elf_id is None:
            return
        defender_state = self._get_elf_state(
            battle_id=battle_id,
            side=payload.defender_side,
            elf_id=payload.defender_elf_id,
        )
        value_damage_delta = self._resolve_value_damage_delta(payload)
        if value_damage_delta is not None:
            value_type = "value"
            value = float(value_damage_delta)
            before_value = (
                float(payload.hp_value_before) if payload.hp_value_before is not None else None
            )
            after_value = (
                float(payload.hp_value_after) if payload.hp_value_after is not None else None
            )
        elif hp_percent_delta is not None:
            value_type = "percent"
            value = hp_percent_delta
            before_value = payload.hp_percent_before
            after_value = payload.hp_percent_after
        elif total_damage is not None:
            value_type = "value"
            value = float(total_damage)
            before_value = (
                float(defender_state.current_hp_value)
                if defender_state is not None and defender_state.current_hp_value is not None
                else None
            )
            after_value = (
                max(before_value - float(total_damage), 0.0)
                if before_value is not None
                else None
            )
        else:
            return

        self.db.add(
            ResourceChangeEvent(
                event_id=f"resource_event_{uuid4().hex}",
                battle_id=battle_id,
                battle_event_id=battle_event_id,
                resource_type="hp",
                change_type="damage",
                source_side=payload.attacker_side,
                source_elf_id=payload.attacker_elf_id,
                target_side=payload.defender_side,
                target_elf_id=payload.defender_elf_id,
                value_type=value_type,
                value=float(value),
                before_value=before_value,
                after_value=after_value,
                confidence=1.0,
                manual_override=True,
            )
        )

    def _update_defender_hp_state(
        self,
        battle: Battle,
        payload: DamageEventCreate,
        total_damage: int | None,
    ) -> None:
        """
        基于手动输入更新防御方生命状态。

        这里只更新观测事实：如果用户传了 hp_percent_after，则写入当前百分比；
        如果传入精确 hp_value_after，则直接写入；否则当前生命值已知且传入总伤害时扣减。
        """
        if payload.defender_side is None or payload.defender_elf_id is None:
            return
        state = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == battle.battle_id,
                BattleElfState.side == payload.defender_side,
                BattleElfState.elf_id == payload.defender_elf_id,
            )
        ).first()
        if state is None:
            return
        if payload.hp_percent_after is not None:
            state.current_hp_percent = payload.hp_percent_after
        if payload.hp_value_after is not None:
            state.current_hp_value = max(payload.hp_value_after, 0)
            panel_stats = self._panel_stats_from_state(state)
            max_hp = panel_stats.hp if panel_stats is not None else None
            if max_hp:
                state.current_hp_percent = round(state.current_hp_value / max_hp * 100, 4)
        elif total_damage is not None and state.current_hp_value is not None:
            state.current_hp_value = max(state.current_hp_value - total_damage, 0)
            panel_stats = self._panel_stats_from_state(state)
            max_hp = panel_stats.hp if panel_stats is not None else None
            if max_hp:
                state.current_hp_percent = round(state.current_hp_value / max_hp * 100, 4)
        if state.current_hp_value == 0 or state.current_hp_percent == 0:
            state.is_defeated = True

    def _process_estimate_observations(
        self,
        *,
        damage_event: DamageEvent,
        payload: DamageEventCreate,
        context: DamageFormulaContext,
        total_damage: int | None,
        hp_percent_delta: float | None,
    ) -> list[dict]:
        """把已确认的伤害事件同步转成实时面板估计观测。"""
        if not payload.sync_observation or total_damage is None:
            return []
        enemy_role, enemy_elf_id = self._resolve_enemy_observation_target(payload)
        if enemy_role is None or enemy_elf_id is None:
            return []
        formula_type = payload.formula_type or "attack"
        if formula_type == "attack":
            if not payload.skill_id:
                return []
            if enemy_role == "defender" and context.attacker_panel_stats is None:
                return []
            if enemy_role == "attacker" and context.defender_panel_stats is None:
                return []
        elif formula_type == "status":
            if enemy_role != "defender" or not payload.effect_id:
                return []
        else:
            return []

        base_payload = context.model_dump(mode="json")
        base_payload.update(
            {
                "enemy_role": enemy_role,
                "skill_confirmed": payload.skill_confirmed,
                "damage_display_type": payload.damage_display_type.value,
                "damage_tolerance": payload.damage_tolerance,
                "percent_tolerance": payload.percent_tolerance,
                "source_damage_event_id": damage_event.event_id,
                "source_battle_event_id": damage_event.battle_event_id,
            }
        )
        estimate_service = EstimateService(self.db)
        results: list[dict] = []
        damage_observation = ObservationEventInput(
            battle_id=damage_event.battle_id,
            enemy_elf_id=enemy_elf_id,
            event_id=f"observation_{uuid4().hex}",
            observation_type=ObservationType.DAMAGE_VALUE,
            observed_value=total_damage,
            payload=base_payload,
        )
        estimate = estimate_service.record_observation(damage_observation, commit=False)
        if estimate is not None:
            results.append(self._estimate_observation_result(estimate, damage_observation))

        if enemy_role == "defender" and hp_percent_delta is not None:
            percent_payload = {
                **base_payload,
                "observed_hp_percent_before": payload.hp_percent_before,
                "observed_hp_percent_after": payload.hp_percent_after,
                "percent_display_mode": (
                    "floor_remaining_percent"
                    if self._is_integer_percent_pair(
                        payload.hp_percent_before,
                        payload.hp_percent_after,
                    )
                    else None
                ),
                "percent_tolerance": (
                    0
                    if self._is_integer_percent_pair(
                        payload.hp_percent_before,
                        payload.hp_percent_after,
                    )
                    else payload.percent_tolerance
                ),
            }
            percent_observation = ObservationEventInput(
                battle_id=damage_event.battle_id,
                enemy_elf_id=enemy_elf_id,
                event_id=f"observation_{uuid4().hex}",
                observation_type=ObservationType.HP_PERCENT_DELTA,
                observed_value=hp_percent_delta,
                payload=percent_payload,
            )
            estimate = estimate_service.record_observation(percent_observation, commit=False)
            if estimate is not None:
                results.append(self._estimate_observation_result(estimate, percent_observation))
        return results

    @staticmethod
    def _estimate_observation_result(estimate: object, observation: ObservationEventInput) -> dict:
        """构造伤害事件返回中的实时估计摘要。"""
        summary = getattr(estimate, "evidence_summary", []) or []
        affected_stats = summary[-1].get("affected_stats", []) if summary else []
        return {
            "status": "estimate_updated",
            "battle_id": observation.battle_id,
            "enemy_elf_id": observation.enemy_elf_id,
            "event_id": observation.event_id,
            "observation_type": observation.observation_type.value,
            "estimate_id": getattr(estimate, "estimate_id", None),
            "affected_stats": affected_stats,
            "inferred_stat_count": len(affected_stats),
        }

    @staticmethod
    def _resolve_enemy_observation_target(
        payload: DamageEventCreate,
    ) -> tuple[str | None, str | None]:
        """判断本次伤害里敌方精灵扮演攻击方还是防御方。"""
        if payload.attacker_side == "enemy" and payload.attacker_elf_id:
            return "attacker", payload.attacker_elf_id
        if payload.defender_side == "enemy" and payload.defender_elf_id:
            return "defender", payload.defender_elf_id
        return None, None

    @staticmethod
    def _is_integer_percent_pair(
        before: float | None,
        after: float | None,
    ) -> bool:
        """敌方血条是整数百分比读数时，按显示剩余百分比取整匹配。"""
        if before is None or after is None:
            return False
        return float(before).is_integer() and float(after).is_integer()
