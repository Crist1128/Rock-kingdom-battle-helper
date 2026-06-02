"""回合阶段自动结算服务。"""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext, PanelStats
from app.calculation.rule_resolver import RuleResolver
from app.core.enums import BattleEventType, DamageDisplayType, EventSource
from app.inference.inference_engine import InferenceEngine
from app.inference.observation_matcher import ObservationEventInput
from app.inference.observation_types import ObservationType
from app.models.battle import Battle, BattleElfState
from app.models.effect import BattleEffectInstance
from app.models.event import BattleEvent, DamageEvent, EffectChangeEvent, ResourceChangeEvent
from app.models.static import EffectDefinition, SkillDefinition
from app.services.snapshot_service import SnapshotService
from app.utils.json import dumps_json, loads_json


class TurnSettlementService:
    """按回合阶段结算当前生效状态并生成系统事件。"""

    END_TURN_ORDER = {
        "effect_poison_mark": 400,
        "effect_poison": 500,
        "effect_burn": 600,
        "effect_leech_seed": 700,
        "effect_freeze": 800,
    }

    def __init__(self, db: Session) -> None:
        self.db = db

    def settle_end_turn(self, battle: Battle, turn_number: int) -> list[dict]:
        """结算回合末 P0 状态，调用方负责最终 commit。"""
        instances = self._load_active_effects(battle.battle_id)
        definitions = self._load_definitions([item.effect_id for item in instances])
        summaries: list[dict] = []

        for instance in sorted(instances, key=self._settlement_order):
            definition = definitions.get(instance.effect_id)
            if definition is None:
                summaries.append(self._skipped(instance, "effect_definition_missing"))
                continue

            hooks = loads_json(definition.formula_hooks_json, [])
            resource_rule = loads_json(definition.resource_modifier_json, {})
            if self._is_end_turn_status_damage(hooks, resource_rule):
                summaries.append(
                    self._settle_status_damage(
                        battle=battle,
                        turn_number=turn_number,
                        instance=instance,
                        definition=definition,
                        resource_rule=resource_rule,
                        settlement_phase="end_turn",
                    )
                )
            elif self._is_freeze_threshold(hooks, resource_rule):
                summaries.append(
                    self._settle_freeze_threshold(
                        battle=battle,
                        turn_number=turn_number,
                        instance=instance,
                        definition=definition,
                    )
                )
            elif (
                resource_rule.get("settlement_type") == "end_turn"
                or "end_turn_apply_effect" in hooks
            ):
                if self._is_end_turn_apply_effect(hooks, resource_rule):
                    summaries.extend(
                        self._settle_end_turn_apply_effect(
                            battle=battle,
                            turn_number=turn_number,
                            instance=instance,
                            definition=definition,
                            resource_rule=resource_rule,
                        )
                    )
                else:
                    summaries.append(self._skipped(instance, "unsupported_end_turn_operation"))

        return summaries

    def settle_switch_in(
        self,
        *,
        battle: Battle,
        turn_number: int,
        side: str,
        elf_id: str,
    ) -> list[dict]:
        """结算入场触发效果，当前 P0 支持棘刺印记。"""
        instances = [
            item
            for item in self._load_active_effects(battle.battle_id)
            if item.owner_scope == "side"
            and item.owner_side == side
            and item.effect_id == "effect_thorn_mark"
        ]
        definitions = self._load_definitions([item.effect_id for item in instances])
        summaries: list[dict] = []
        for instance in instances:
            definition = definitions.get(instance.effect_id)
            if definition is None:
                summaries.append(self._skipped(instance, "effect_definition_missing"))
                continue
            resource_rule = loads_json(definition.resource_modifier_json, {})
            if resource_rule.get("settlement_type") != "switch_in":
                summaries.append(self._skipped(instance, "not_switch_in_settlement"))
                continue
            target = self._get_state(battle.battle_id, side, elf_id)
            if target is None:
                summaries.append(self._skipped(instance, "target_state_missing"))
                continue
            summaries.append(
                self._settle_status_damage(
                    battle=battle,
                    turn_number=turn_number,
                    instance=instance,
                    definition=definition,
                    resource_rule=resource_rule,
                    settlement_phase="switch_in",
                    target_override=target,
                )
            )
        return summaries

    def settle_post_attack(
        self,
        *,
        battle: Battle,
        turn_number: int,
        trigger_battle_event_id: str,
        attacker_side: str | None,
        attacker_elf_id: str | None,
        defender_side: str | None,
        defender_elf_id: str | None,
        trigger_skill_id: str | None,
    ) -> list[dict]:
        """结算攻击后触发效果，当前 P0 支持星陨印记。"""
        if not attacker_side or not attacker_elf_id or not defender_side or not defender_elf_id:
            return []
        attacker = self._get_state(battle.battle_id, attacker_side, attacker_elf_id)
        defender = self._get_state(battle.battle_id, defender_side, defender_elf_id)
        if attacker is None or defender is None:
            return []

        instances = [
            item
            for item in self._load_active_effects(battle.battle_id)
            if item.effect_id == "effect_starfall_mark"
            and item.owner_scope == "side"
            and item.owner_side == defender_side
        ]
        definitions = self._load_definitions([item.effect_id for item in instances])
        summaries: list[dict] = []
        for instance in instances:
            definition = definitions.get(instance.effect_id)
            if definition is None:
                summaries.append(self._skipped(instance, "effect_definition_missing"))
                continue
            resource_rule = loads_json(definition.resource_modifier_json, {})
            if resource_rule.get("settlement_type") != "post_attack":
                summaries.append(self._skipped(instance, "not_post_attack_settlement"))
                continue
            summaries.append(
                self._settle_starfall_damage(
                    battle=battle,
                    turn_number=turn_number,
                    trigger_battle_event_id=trigger_battle_event_id,
                    instance=instance,
                    definition=definition,
                    resource_rule=resource_rule,
                    attacker=attacker,
                    defender=defender,
                    trigger_skill_id=trigger_skill_id,
                )
            )
        return summaries

    def _settle_status_damage(
        self,
        *,
        battle: Battle,
        turn_number: int,
        instance: BattleEffectInstance,
        definition: EffectDefinition,
        resource_rule: dict,
        settlement_phase: str,
        target_override: BattleElfState | None = None,
    ) -> dict:
        target = target_override or self._resolve_target_state(battle, instance)
        if target is None:
            return self._skipped(instance, "target_state_missing")

        max_hp = self._max_hp(target)
        if max_hp is None:
            return self._skipped(instance, "defender_max_hp_missing")

        source_side, source_elf_id = self._resolve_source(battle, instance, target.side)
        battle_event_id = f"event_{uuid4().hex}"
        damage_event_id = f"damage_event_{uuid4().hex}"
        context = DamageFormulaContext(
            battle_id=battle.battle_id,
            damage_event_id=damage_event_id,
            battle_event_id=battle_event_id,
            formula_type="status",
            attacker_side=source_side,
            attacker_elf_id=source_elf_id,
            defender_side=target.side,
            defender_elf_id=target.elf_id,
            skill_element_type=resource_rule.get("element_type"),
            damage_display_type=DamageDisplayType.SPECIAL_DAMAGE.value,
            defender_max_hp=max_hp,
            defender_hp_percent=target.current_hp_percent,
            effect_id=instance.effect_id,
            effect_layers=instance.layers,
            notes=f"{settlement_phase} settlement from {instance.effect_id}",
        )
        if resource_rule.get("uses_type_effectiveness"):
            RuleResolver(self.db).resolve_damage_context(context, {"resolve_rules": True})

        result = DamageCalculator().calculate(context)
        if result.status != "calculated" or result.damage_value is None:
            return {
                **self._base_summary(instance),
                "status": result.status,
                "reason": ",".join(result.missing_parts or result.unknown_factors),
                "damage_value": result.damage_value,
            }

        hp_change = self._apply_hp_damage(target, result.damage_value, max_hp)
        battle_event = BattleEvent(
            event_id=battle_event_id,
            battle_id=battle.battle_id,
            turn_number=turn_number,
            event_type=BattleEventType.DAMAGE.value,
            actor_side=source_side,
            actor_elf_id=source_elf_id,
            target_side=target.side,
            target_elf_id=target.elf_id,
            source=EventSource.SYSTEM_CALCULATED.value,
            manual_override=False,
            payload_json=dumps_json(
                {
                    "settlement_phase": settlement_phase,
                    "effect_instance_id": instance.instance_id,
                    "effect_id": instance.effect_id,
                    "formula_type": "status",
                    "calculation_status": result.status,
                    "explanation": result.explanation,
                }
            ),
            notes=f"{self._phase_label(settlement_phase)}自动结算：{definition.effect_name}",
        )
        self.db.add(battle_event)
        self.db.add(
            DamageEvent(
                event_id=damage_event_id,
                battle_id=battle.battle_id,
                battle_event_id=battle_event.event_id,
                attacker_side=source_side,
                attacker_elf_id=source_elf_id,
                defender_side=target.side,
                defender_elf_id=target.elf_id,
                damage_display_type=DamageDisplayType.SPECIAL_DAMAGE.value,
                damage_value=result.damage_value,
                hp_percent_before=hp_change["hp_percent_before"],
                hp_percent_after=hp_change["hp_percent_after"],
                hp_percent_delta=hp_change["hp_percent_delta"],
                enemy_hp_percent_damage=hp_change["hp_percent_delta"],
                type_effectiveness=float(Decimal(str(context.type_multiplier))),
                special_formula_id=definition.special_rule_id or instance.effect_id,
                calculation_confidence=result.confidence,
                manual_override=False,
            )
        )
        self._create_hp_resource_event(
            battle_id=battle.battle_id,
            battle_event_id=battle_event.event_id,
            source_side=source_side,
            source_elf_id=source_elf_id,
            target_side=target.side,
            target_elf_id=target.elf_id,
            change_type="damage",
            value=float(result.damage_value),
            before_value=hp_change["hp_value_before"],
            after_value=hp_change["hp_value_after"],
            confidence=result.confidence,
        )

        if resource_rule.get("heal_opponent_by_damage"):
            self._apply_secondary_heal(
                battle=battle,
                battle_event_id=battle_event.event_id,
                source_side=source_side,
                source_elf_id=source_elf_id,
                excluded_target=target,
                heal_value=result.damage_value,
                confidence=result.confidence,
            )

        layer_summary = self._apply_after_settlement(
            instance=instance,
            definition=definition,
            battle_event_id=battle_event.event_id,
            turn_number=turn_number,
            resource_rule=resource_rule,
        )
        self.db.flush()
        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle.battle_id,
            turn_number,
            source_event_id=battle_event.event_id,
            commit=False,
        )
        battle_event.snapshot_id = snapshot.snapshot_id
        context.snapshot_id = snapshot.snapshot_id
        context.snapshot_payload = loads_json(snapshot.full_snapshot_json, [])
        damage_event = self.db.get(DamageEvent, damage_event_id)
        if damage_event is not None:
            damage_event.formula_context_json = dumps_json(context)

        observation_result = self._process_damage_observation(
            battle_id=battle.battle_id,
            target=target,
            event_id=damage_event_id,
            observed_damage=result.damage_value,
            payload={
                "formula_type": "status",
                "effect_id": instance.effect_id,
                "effect_layers": result.explanation.get("layers", instance.layers),
                "skill_element_type": resource_rule.get("element_type"),
                "resolve_rules": True,
                "observed_damage_value": result.damage_value,
            },
        )
        summary = {
            **self._base_summary(instance),
            "status": "settled",
            "battle_event_id": battle_event.event_id,
            "snapshot_id": snapshot.snapshot_id,
            "settlement_phase": settlement_phase,
            "target_side": target.side,
            "target_elf_id": target.elf_id,
            "damage_value": result.damage_value,
            "type_multiplier": str(context.type_multiplier),
            **layer_summary,
        }
        if observation_result is not None:
            summary["observation_result"] = observation_result
        return summary

    def _settle_starfall_damage(
        self,
        *,
        battle: Battle,
        turn_number: int,
        trigger_battle_event_id: str,
        instance: BattleEffectInstance,
        definition: EffectDefinition,
        resource_rule: dict,
        attacker: BattleElfState,
        defender: BattleElfState,
        trigger_skill_id: str | None,
    ) -> dict:
        attacker_panel = self._panel_stats(attacker)
        defender_panel = self._panel_stats(defender)
        if attacker_panel is None:
            return self._skipped(instance, "attacker_panel_stats_missing")
        if defender_panel is None:
            return self._skipped(instance, "defender_panel_stats_missing")

        skill = self.db.get(SkillDefinition, trigger_skill_id) if trigger_skill_id else None
        battle_event_id = f"event_{uuid4().hex}"
        damage_event_id = f"damage_event_{uuid4().hex}"
        context = DamageFormulaContext(
            battle_id=battle.battle_id,
            damage_event_id=damage_event_id,
            battle_event_id=battle_event_id,
            formula_type="starfall",
            attacker_side=attacker.side,
            attacker_elf_id=attacker.elf_id,
            defender_side=defender.side,
            defender_elf_id=defender.elf_id,
            trigger_skill_id=trigger_skill_id,
            trigger_skill_element_type=skill.element_type if skill is not None else None,
            trigger_skill_category=skill.skill_category if skill is not None else None,
            starfall_element_type=str(resource_rule.get("element_type") or "幻"),
            attacker_panel_stats=attacker_panel,
            defender_panel_stats=defender_panel,
            defender_max_hp=defender_panel.hp,
            defender_hp_percent=defender.current_hp_percent,
            effect_id=instance.effect_id,
            effect_layers=instance.layers,
            damage_display_type=DamageDisplayType.SPECIAL_DAMAGE.value,
            notes=f"post_attack settlement from {instance.effect_id}",
        )
        RuleResolver(self.db).resolve_damage_context(context, {"resolve_rules": True})
        result = DamageCalculator().calculate(context)
        if result.status != "calculated" or result.damage_value is None:
            return {
                **self._base_summary(instance),
                "status": result.status,
                "settlement_phase": "post_attack",
                "reason": ",".join(result.missing_parts or result.unknown_factors),
                "damage_value": result.damage_value,
            }

        hp_change = self._apply_hp_damage(defender, result.damage_value, defender_panel.hp)
        battle_event = BattleEvent(
            event_id=battle_event_id,
            battle_id=battle.battle_id,
            turn_number=turn_number,
            event_type=BattleEventType.DAMAGE.value,
            actor_side=attacker.side,
            actor_elf_id=attacker.elf_id,
            target_side=defender.side,
            target_elf_id=defender.elf_id,
            source=EventSource.SYSTEM_CALCULATED.value,
            manual_override=False,
            payload_json=dumps_json(
                {
                    "settlement_phase": "post_attack",
                    "trigger_battle_event_id": trigger_battle_event_id,
                    "effect_instance_id": instance.instance_id,
                    "effect_id": instance.effect_id,
                    "formula_type": "starfall",
                    "calculation_status": result.status,
                    "explanation": result.explanation,
                }
            ),
            notes=f"攻击后自动结算：{definition.effect_name}",
        )
        self.db.add(battle_event)
        self.db.add(
            DamageEvent(
                event_id=damage_event_id,
                battle_id=battle.battle_id,
                battle_event_id=battle_event.event_id,
                attacker_side=attacker.side,
                attacker_elf_id=attacker.elf_id,
                defender_side=defender.side,
                defender_elf_id=defender.elf_id,
                skill_id=trigger_skill_id,
                damage_display_type=DamageDisplayType.SPECIAL_DAMAGE.value,
                damage_value=result.damage_value,
                hp_percent_before=hp_change["hp_percent_before"],
                hp_percent_after=hp_change["hp_percent_after"],
                hp_percent_delta=hp_change["hp_percent_delta"],
                enemy_hp_percent_damage=hp_change["hp_percent_delta"],
                type_effectiveness=float(Decimal(str(context.type_multiplier))),
                special_formula_id=definition.special_rule_id or instance.effect_id,
                calculation_confidence=result.confidence,
                manual_override=False,
            )
        )
        self._create_hp_resource_event(
            battle_id=battle.battle_id,
            battle_event_id=battle_event.event_id,
            source_side=attacker.side,
            source_elf_id=attacker.elf_id,
            target_side=defender.side,
            target_elf_id=defender.elf_id,
            change_type="damage",
            value=float(result.damage_value),
            before_value=hp_change["hp_value_before"],
            after_value=hp_change["hp_value_after"],
            confidence=result.confidence,
        )
        layer_summary = self._apply_after_settlement(
            instance=instance,
            definition=definition,
            battle_event_id=battle_event.event_id,
            turn_number=turn_number,
            resource_rule=resource_rule,
        )
        self.db.flush()
        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle.battle_id,
            turn_number,
            source_event_id=battle_event.event_id,
            commit=False,
        )
        battle_event.snapshot_id = snapshot.snapshot_id
        context.snapshot_id = snapshot.snapshot_id
        context.snapshot_payload = loads_json(snapshot.full_snapshot_json, [])
        damage_event = self.db.get(DamageEvent, damage_event_id)
        if damage_event is not None:
            damage_event.formula_context_json = dumps_json(context)

        observation_payload = {
            "formula_type": "starfall",
            "effect_id": instance.effect_id,
            "effect_layers": result.explanation.get("layers", instance.layers),
            "trigger_skill_id": trigger_skill_id,
            "trigger_skill_element_type": context.trigger_skill_element_type,
            "trigger_skill_category": context.trigger_skill_category,
            "attacker_panel_stats": attacker_panel.model_dump(),
            "resolve_rules": True,
            "observed_damage_value": result.damage_value,
        }
        observation_result = self._process_damage_observation(
            battle_id=battle.battle_id,
            target=defender,
            event_id=damage_event_id,
            observed_damage=result.damage_value,
            payload=observation_payload,
        )
        summary = {
            **self._base_summary(instance),
            "status": "settled",
            "settlement_phase": "post_attack",
            "battle_event_id": battle_event.event_id,
            "snapshot_id": snapshot.snapshot_id,
            "target_side": defender.side,
            "target_elf_id": defender.elf_id,
            "damage_value": result.damage_value,
            "type_multiplier": str(context.type_multiplier),
            **layer_summary,
        }
        if observation_result is not None:
            summary["observation_result"] = observation_result
        return summary

    def _settle_freeze_threshold(
        self,
        *,
        battle: Battle,
        turn_number: int,
        instance: BattleEffectInstance,
        definition: EffectDefinition,
    ) -> dict:
        target = self._resolve_target_state(battle, instance)
        if target is None:
            return self._skipped(instance, "target_state_missing")

        context = DamageFormulaContext(
            battle_id=battle.battle_id,
            formula_type="status",
            defender_side=target.side,
            defender_elf_id=target.elf_id,
            defender_hp_percent=target.current_hp_percent,
            effect_id=instance.effect_id,
            effect_layers=instance.layers,
            notes=f"end_turn threshold check from {instance.effect_id}",
        )
        result = DamageCalculator().calculate(context)
        triggered = result.explanation.get("defeated_by_freeze")
        if triggered is None:
            return {
                **self._base_summary(instance),
                "status": result.status,
                "reason": ",".join(result.unknown_factors or result.missing_parts),
            }
        if not triggered:
            return {
                **self._base_summary(instance),
                "status": "checked",
                "triggered": False,
                "threshold_percent": result.explanation.get("threshold_percent"),
            }

        before_percent = target.current_hp_percent
        before_value = target.current_hp_value
        target.current_hp_percent = 0
        target.current_hp_value = 0 if target.current_hp_value is not None else None
        target.is_defeated = True

        battle_event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle.battle_id,
            turn_number=turn_number,
            event_type=BattleEventType.EFFECT_TRIGGER.value,
            target_side=target.side,
            target_elf_id=target.elf_id,
            source=EventSource.SYSTEM_CALCULATED.value,
            manual_override=False,
            payload_json=dumps_json(
                {
                    "settlement_phase": "end_turn",
                    "effect_instance_id": instance.instance_id,
                    "effect_id": instance.effect_id,
                    "formula_type": "status",
                    "explanation": result.explanation,
                }
            ),
            notes=f"回合末自动结算：{definition.effect_name} 阈值力竭",
        )
        self.db.add(battle_event)
        self._create_hp_resource_event(
            battle_id=battle.battle_id,
            battle_event_id=battle_event.event_id,
            source_side=None,
            source_elf_id=None,
            target_side=target.side,
            target_elf_id=target.elf_id,
            change_type="damage",
            value_type="percent" if before_percent is not None else "value",
            value=float(before_percent if before_percent is not None else before_value or 0),
            before_value=before_percent if before_percent is not None else before_value,
            after_value=0 if before_percent is not None else target.current_hp_value,
            confidence=result.confidence,
        )
        self.db.flush()
        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle.battle_id,
            turn_number,
            source_event_id=battle_event.event_id,
            commit=False,
        )
        battle_event.snapshot_id = snapshot.snapshot_id

        return {
            **self._base_summary(instance),
            "status": "settled",
            "battle_event_id": battle_event.event_id,
            "snapshot_id": snapshot.snapshot_id,
            "target_side": target.side,
            "target_elf_id": target.elf_id,
            "triggered": True,
            "hp_percent_before": before_percent,
            "hp_percent_after": 0,
        }

    def _settle_end_turn_apply_effect(
        self,
        *,
        battle: Battle,
        turn_number: int,
        instance: BattleEffectInstance,
        definition: EffectDefinition,
        resource_rule: dict,
    ) -> list[dict]:
        """执行回合末施加状态类天气效果，当前用于暴风雪施加冻结。"""
        if resource_rule.get("operation") != "apply_effect":
            return [self._skipped(instance, "unsupported_end_turn_operation")]
        effect_id = resource_rule.get("effect_id")
        if not effect_id:
            return [self._skipped(instance, "target_effect_id_missing")]
        target_definition = self.db.get(EffectDefinition, str(effect_id))
        if target_definition is None:
            return [self._skipped(instance, f"target_effect_definition_missing:{effect_id}")]

        targets = self._resolve_apply_effect_targets(battle, resource_rule)
        if not targets:
            return [self._skipped(instance, "apply_effect_targets_missing")]

        summaries: list[dict] = []
        layers = int(resource_rule.get("layers", 1) or 1)
        for target in targets:
            summaries.append(
                self._apply_effect_from_settlement(
                    battle=battle,
                    turn_number=turn_number,
                    source_instance=instance,
                    source_definition=definition,
                    target_definition=target_definition,
                    target=target,
                    layers=layers,
                    settlement_phase="end_turn",
                )
            )
        return summaries

    def _apply_effect_from_settlement(
        self,
        *,
        battle: Battle,
        turn_number: int,
        source_instance: BattleEffectInstance,
        source_definition: EffectDefinition,
        target_definition: EffectDefinition,
        target: BattleElfState,
        layers: int,
        settlement_phase: str,
    ) -> dict:
        event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle.battle_id,
            turn_number=turn_number,
            event_type=BattleEventType.EFFECT_APPLY.value,
            actor_side=source_instance.owner_side,
            actor_elf_id=source_instance.owner_elf_id,
            target_side=target.side,
            target_elf_id=target.elf_id,
            source=EventSource.SYSTEM_CALCULATED.value,
            manual_override=False,
            payload_json=dumps_json(
                {
                    "settlement_phase": settlement_phase,
                    "source_effect_instance_id": source_instance.instance_id,
                    "source_effect_id": source_instance.effect_id,
                    "effect_id": target_definition.effect_id,
                    "layers": layers,
                }
            ),
            notes=(
                f"{self._phase_label(settlement_phase)}自动结算："
                f"{source_definition.effect_name} 施加 {target_definition.effect_name}"
            ),
        )
        self.db.add(event)
        existing = self._find_active_effect_instance(
            battle_id=battle.battle_id,
            effect_id=target_definition.effect_id,
            owner_scope="elf",
            owner_side=target.side,
            owner_elf_id=target.elf_id,
        )
        layers_before = existing.layers if existing is not None else None
        if existing is None:
            applied = BattleEffectInstance(
                instance_id=f"effect_instance_{uuid4().hex}",
                battle_id=battle.battle_id,
                effect_id=target_definition.effect_id,
                category=target_definition.category,
                owner_scope="elf",
                owner_side=target.side,
                owner_elf_id=target.elf_id,
                source_side=source_instance.owner_side,
                source_elf_id=source_instance.owner_elf_id,
                source_event_id=event.event_id,
                layers=self._cap_layers(layers, target_definition.max_layers),
                remaining_turns=target_definition.default_duration_turns,
                remaining_uses=target_definition.default_duration_uses,
                is_active=True,
                applied_turn=turn_number,
                expire_turn=self._expire_turn(turn_number, target_definition),
                last_updated_turn=turn_number,
                recognition_source=EventSource.SYSTEM_CALCULATED.value,
                recognition_confidence=1.0,
                manual_override=False,
            )
            self.db.add(applied)
            layers_after = applied.layers
        else:
            applied = existing
            if target_definition.stack_rule in {"add", "add_layers"}:
                applied.layers = self._cap_layers(
                    applied.layers + layers,
                    target_definition.max_layers,
                )
            else:
                applied.layers = self._cap_layers(layers, target_definition.max_layers)
            applied.remaining_turns = target_definition.default_duration_turns
            applied.remaining_uses = target_definition.default_duration_uses
            applied.last_updated_turn = turn_number
            applied.is_active = True
            layers_after = applied.layers

        self.db.add(
            EffectChangeEvent(
                event_id=f"effect_change_event_{uuid4().hex}",
                battle_id=battle.battle_id,
                battle_event_id=event.event_id,
                turn_number=turn_number,
                change_type="settlement_apply" if layers_before is None else "settlement_stack",
                effect_instance_id=applied.instance_id,
                effect_id=target_definition.effect_id,
                effect_name=target_definition.effect_name,
                category=target_definition.category,
                target_side=target.side,
                target_elf_id=target.elf_id,
                owner_scope="elf",
                layers_before=layers_before,
                layers_after=layers_after,
                duration_before=None,
                duration_after=applied.remaining_turns,
                source_elf_id=source_instance.owner_elf_id,
                reason=f"{settlement_phase}_apply_effect:{source_instance.effect_id}",
                source=EventSource.SYSTEM_CALCULATED.value,
                manual_override=False,
            )
        )
        self.db.flush()
        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle.battle_id,
            turn_number,
            source_event_id=event.event_id,
            commit=False,
        )
        event.snapshot_id = snapshot.snapshot_id
        return {
            "status": "settled",
            "settlement_phase": settlement_phase,
            "operation": "apply_effect",
            "source_effect_instance_id": source_instance.instance_id,
            "source_effect_id": source_instance.effect_id,
            "effect_instance_id": applied.instance_id,
            "effect_id": target_definition.effect_id,
            "target_side": target.side,
            "target_elf_id": target.elf_id,
            "layers_before": layers_before,
            "layers_after": layers_after,
            "battle_event_id": event.event_id,
            "snapshot_id": snapshot.snapshot_id,
        }

    def _load_active_effects(self, battle_id: str) -> list[BattleEffectInstance]:
        return list(
            self.db.scalars(
                select(BattleEffectInstance).where(
                    BattleEffectInstance.battle_id == battle_id,
                    BattleEffectInstance.is_active.is_(True),
                )
            ).all()
        )

    def _load_definitions(self, effect_ids: list[str]) -> dict[str, EffectDefinition]:
        if not effect_ids:
            return {}
        return {
            item.effect_id: item
            for item in self.db.scalars(
                select(EffectDefinition).where(EffectDefinition.effect_id.in_(set(effect_ids)))
            ).all()
        }

    def _settlement_order(self, instance: BattleEffectInstance) -> tuple[int, int, str]:
        order = self.END_TURN_ORDER.get(instance.effect_id, 900)
        applied_turn = instance.applied_turn if instance.applied_turn is not None else 0
        return (order, applied_turn, instance.instance_id)

    @staticmethod
    def _is_end_turn_status_damage(hooks: list, resource_rule: dict) -> bool:
        return (
            "end_turn_status_damage" in hooks
            and resource_rule.get("settlement_type") == "end_turn"
            and resource_rule.get("damage_kind") in {"status", "true"}
        )

    @staticmethod
    def _is_freeze_threshold(hooks: list, resource_rule: dict) -> bool:
        return (
            "freeze_threshold_check" in hooks
            or resource_rule.get("damage_kind") == "threshold_defeat"
        )

    @staticmethod
    def _is_end_turn_apply_effect(hooks: list, resource_rule: dict) -> bool:
        return (
            "end_turn_apply_effect" in hooks
            and resource_rule.get("settlement_type") == "end_turn"
            and resource_rule.get("operation") == "apply_effect"
        )

    def _resolve_apply_effect_targets(
        self,
        battle: Battle,
        resource_rule: dict,
    ) -> list[BattleElfState]:
        target = resource_rule.get("target")
        targets: list[BattleElfState] = []
        if target == "both_active_elves":
            for side, elf_id in (
                ("self", battle.self_active_elf_id),
                ("enemy", battle.enemy_active_elf_id),
            ):
                if elf_id is None:
                    continue
                state = self._get_state(battle.battle_id, side, elf_id)
                if state is not None:
                    targets.append(state)
        return targets

    def _resolve_target_state(
        self,
        battle: Battle,
        instance: BattleEffectInstance,
    ) -> BattleElfState | None:
        if instance.owner_scope == "elf" and instance.owner_side and instance.owner_elf_id:
            return self._get_state(battle.battle_id, instance.owner_side, instance.owner_elf_id)
        if instance.owner_scope == "side" and instance.owner_side:
            active_elf_id = (
                battle.self_active_elf_id
                if instance.owner_side == "self"
                else battle.enemy_active_elf_id
            )
            if active_elf_id is None:
                return None
            return self._get_state(battle.battle_id, instance.owner_side, active_elf_id)
        return None

    def _get_state(self, battle_id: str, side: str, elf_id: str) -> BattleElfState | None:
        return self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == battle_id,
                BattleElfState.side == side,
                BattleElfState.elf_id == elf_id,
            )
        ).first()

    def _find_active_effect_instance(
        self,
        *,
        battle_id: str,
        effect_id: str,
        owner_scope: str,
        owner_side: str | None,
        owner_elf_id: str | None,
    ) -> BattleEffectInstance | None:
        return self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle_id,
                BattleEffectInstance.effect_id == effect_id,
                BattleEffectInstance.owner_scope == owner_scope,
                BattleEffectInstance.owner_side == owner_side,
                BattleEffectInstance.owner_elf_id == owner_elf_id,
                BattleEffectInstance.is_active.is_(True),
            )
        ).first()

    def _resolve_source(
        self,
        battle: Battle,
        instance: BattleEffectInstance,
        target_side: str,
    ) -> tuple[str | None, str | None]:
        if instance.source_side is not None or instance.source_elf_id is not None:
            return instance.source_side, instance.source_elf_id
        source_side = self._opposite_side(target_side)
        source_elf_id = (
            battle.self_active_elf_id if source_side == "self" else battle.enemy_active_elf_id
        )
        return source_side, source_elf_id

    @staticmethod
    def _opposite_side(side: str) -> str:
        return "enemy" if side == "self" else "self"

    @staticmethod
    def _max_hp(state: BattleElfState) -> int | None:
        stats = loads_json(state.panel_stats_json, {})
        if not isinstance(stats, dict):
            return None
        value = stats.get("hp")
        if value is None:
            return None
        try:
            hp = int(value)
        except (TypeError, ValueError):
            return None
        return hp if hp > 0 else None

    @staticmethod
    def _panel_stats(state: BattleElfState) -> PanelStats | None:
        stats = loads_json(state.panel_stats_json, {})
        if not isinstance(stats, dict):
            return None
        try:
            return PanelStats(
                hp=int(stats["hp"]),
                physical_attack=int(stats["physical_attack"]),
                physical_defense=int(stats["physical_defense"]),
                magic_attack=int(stats["magic_attack"]),
                magic_defense=int(stats["magic_defense"]),
                speed=int(stats["speed"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _apply_hp_damage(
        state: BattleElfState,
        damage_value: int,
        max_hp: int,
    ) -> dict[str, float | int | None]:
        before_value = state.current_hp_value
        before_percent = state.current_hp_percent
        after_value = None
        if state.current_hp_value is not None:
            state.current_hp_value = max(state.current_hp_value - damage_value, 0)
            after_value = state.current_hp_value

        percent_delta = round((damage_value / max_hp) * 100, 4)
        if before_percent is not None:
            state.current_hp_percent = max(round(before_percent - percent_delta, 4), 0.0)
        elif after_value is not None:
            state.current_hp_percent = round((after_value / max_hp) * 100, 4)
        state.is_defeated = state.current_hp_value == 0 or state.current_hp_percent == 0
        return {
            "hp_value_before": before_value,
            "hp_value_after": state.current_hp_value,
            "hp_percent_before": before_percent,
            "hp_percent_after": state.current_hp_percent,
            "hp_percent_delta": percent_delta,
        }

    def _apply_secondary_heal(
        self,
        *,
        battle: Battle,
        battle_event_id: str,
        source_side: str | None,
        source_elf_id: str | None,
        excluded_target: BattleElfState,
        heal_value: int,
        confidence: float,
    ) -> None:
        heal_target = None
        if source_side and source_elf_id:
            heal_target = self._get_state(battle.battle_id, source_side, source_elf_id)
        if heal_target is None:
            heal_side = self._opposite_side(excluded_target.side)
            heal_elf_id = (
                battle.self_active_elf_id if heal_side == "self" else battle.enemy_active_elf_id
            )
            if heal_elf_id is not None:
                heal_target = self._get_state(battle.battle_id, heal_side, heal_elf_id)
        if heal_target is None:
            return

        max_hp = self._max_hp(heal_target)
        before_value = heal_target.current_hp_value
        if heal_target.current_hp_value is not None:
            new_value = heal_target.current_hp_value + heal_value
            heal_target.current_hp_value = (
                min(new_value, max_hp) if max_hp is not None else new_value
            )
        if max_hp is not None and heal_target.current_hp_value is not None:
            heal_target.current_hp_percent = round((heal_target.current_hp_value / max_hp) * 100, 4)
        heal_target.is_defeated = (
            heal_target.current_hp_value == 0 or heal_target.current_hp_percent == 0
        )
        self._create_hp_resource_event(
            battle_id=battle.battle_id,
            battle_event_id=battle_event_id,
            source_side=excluded_target.side,
            source_elf_id=excluded_target.elf_id,
            target_side=heal_target.side,
            target_elf_id=heal_target.elf_id,
            change_type="heal",
            value=float(heal_value),
            before_value=before_value,
            after_value=heal_target.current_hp_value,
            confidence=confidence,
        )

    def _create_hp_resource_event(
        self,
        *,
        battle_id: str,
        battle_event_id: str,
        source_side: str | None,
        source_elf_id: str | None,
        target_side: str | None,
        target_elf_id: str | None,
        change_type: str,
        value: float,
        before_value: float | int | None,
        after_value: float | int | None,
        confidence: float,
        value_type: str = "value",
    ) -> None:
        self.db.add(
            ResourceChangeEvent(
                event_id=f"resource_event_{uuid4().hex}",
                battle_id=battle_id,
                battle_event_id=battle_event_id,
                resource_type="hp",
                change_type=change_type,
                source_side=source_side,
                source_elf_id=source_elf_id,
                target_side=target_side,
                target_elf_id=target_elf_id,
                value_type=value_type,
                value=value,
                before_value=float(before_value) if before_value is not None else None,
                after_value=float(after_value) if after_value is not None else None,
                confidence=confidence,
                manual_override=False,
            )
        )

    def _process_damage_observation(
        self,
        *,
        battle_id: str,
        target: BattleElfState,
        event_id: str,
        observed_damage: int,
        payload: dict,
    ) -> dict | None:
        """把自动结算伤害写入候选软评分；只有敌方作为受击方时才有候选池。"""
        if target.side != "enemy":
            return None
        observation = ObservationEventInput(
            battle_id=battle_id,
            enemy_elf_id=target.elf_id,
            event_id=event_id,
            observation_type=ObservationType.DAMAGE_VALUE,
            observed_value=observed_damage,
            payload=payload,
            allow_hard_exclude=False,
        )
        return InferenceEngine(self.db).process_observation_event(observation, commit=False)

    def _apply_after_settlement(
        self,
        *,
        instance: BattleEffectInstance,
        definition: EffectDefinition,
        battle_event_id: str,
        turn_number: int,
        resource_rule: dict,
    ) -> dict:
        rule = resource_rule.get("after_settlement") or {}
        layer_change = rule.get("layer_change")
        if layer_change not in {"halve_floor", "clear"}:
            return {"layers_before": instance.layers, "layers_after": instance.layers}

        layers_before = instance.layers
        if layer_change == "halve_floor":
            instance.layers = max(instance.layers // 2, 0)
            if instance.layers <= 0:
                instance.is_active = False
        elif layer_change == "clear":
            instance.layers = 0
            instance.is_active = False
        instance.last_updated_turn = turn_number
        self.db.add(
            EffectChangeEvent(
                event_id=f"effect_change_event_{uuid4().hex}",
                battle_id=instance.battle_id,
                battle_event_id=battle_event_id,
                turn_number=turn_number,
                change_type="settlement_layer_change",
                effect_instance_id=instance.instance_id,
                effect_id=instance.effect_id,
                effect_name=definition.effect_name,
                category=definition.category,
                target_side=instance.owner_side,
                target_elf_id=instance.owner_elf_id,
                target_skill_slot_id=instance.owner_skill_slot_id,
                owner_scope=instance.owner_scope,
                layers_before=layers_before,
                layers_after=instance.layers,
                duration_before=instance.remaining_turns,
                duration_after=instance.remaining_turns,
                source_skill_id=instance.source_skill_id,
                source_elf_id=instance.source_elf_id,
                reason=f"end_turn_after_settlement:{layer_change}",
                source=EventSource.SYSTEM_CALCULATED.value,
                manual_override=False,
            )
        )
        return {"layers_before": layers_before, "layers_after": instance.layers}

    @staticmethod
    def _cap_layers(layers: int, max_layers: int | None) -> int:
        if max_layers is None:
            return max(layers, 0)
        return min(max(layers, 0), max_layers)

    @staticmethod
    def _expire_turn(turn_number: int, definition: EffectDefinition) -> int | None:
        if definition.default_duration_turns is None:
            return None
        return turn_number + definition.default_duration_turns

    @staticmethod
    def _phase_label(settlement_phase: str) -> str:
        labels = {
            "end_turn": "回合末",
            "switch_in": "入场",
            "post_attack": "攻击后",
        }
        return labels.get(settlement_phase, settlement_phase)

    def _skipped(self, instance: BattleEffectInstance, reason: str) -> dict:
        return {**self._base_summary(instance), "status": "skipped", "reason": reason}

    @staticmethod
    def _base_summary(instance: BattleEffectInstance) -> dict:
        return {
            "effect_instance_id": instance.instance_id,
            "effect_id": instance.effect_id,
            "owner_scope": instance.owner_scope,
            "owner_side": instance.owner_side,
            "owner_elf_id": instance.owner_elf_id,
            "layers": instance.layers,
        }
