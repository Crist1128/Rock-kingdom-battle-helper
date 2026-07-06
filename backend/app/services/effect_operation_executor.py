"""技能效果操作执行器。

本模块负责把 SkillDefinition.effect_operations_json 中的结构化操作落到战斗运行时。
阶段 D 支持常见状态、天气和资源操作；对条件不明确或上下文不足的分支只记录
skipped/unknown，不强行改写状态。
"""

from math import floor
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculation.formula_context import DamageFormulaContext
from app.calculation.hit_rule_resolver import HitRuleResolver
from app.core.enums import EventSource, OwnerScope, Side
from app.models.battle import Battle, BattleElfState, BattleSkillSlot
from app.models.effect import BattleEffectInstance
from app.models.event import BattleEvent, EffectChangeEvent, ResourceChangeEvent
from app.models.static import EffectDefinition, SkillDefinition
from app.utils.json import dumps_json, loads_json


class EffectOperationExecutor:
    """执行技能定义中的结构化效果操作。"""

    SUPPORTED_OPERATIONS = {
        "apply_effect",
        "add_layers",
        "dynamic_apply_effect",
        "remove_effect",
        "clear_effects",
        "change_weather",
        "resource_change",
        "resource_change_multi_target",
        "resource_change_from_effect_layers",
        "heal_from_damage_dealt",
        "convert_effect",
        "convert_effects_by_polarity",
        "swap_hp_percent",
        "trigger_status_damage_now",
        "multiply_layers",
        "multiply_layers_by_polarity",
        "clear_effect_layers",
        "conditional_branch",
        "modify_skill_slots",
        "prepare_next_switch_in_effect",
        "interrupt_action",
    }
    ALWAYS_CONDITIONS = {None, "", "always", "normal", "on_skill_use"}

    def __init__(self, db: Session) -> None:
        self.db = db

    def execute_for_skill_event(self, battle_event: BattleEvent) -> list[dict]:
        """根据技能事件执行 effect_operations_json，调用方负责 commit 和快照。"""
        if battle_event.skill_id is None:
            return []
        skill = self.db.get(SkillDefinition, battle_event.skill_id)
        if skill is None or skill.deleted_at is not None:
            return [
                {
                    "status": "skipped",
                    "reason": "skill_definition_missing",
                    "skill_id": battle_event.skill_id,
                }
            ]

        operations = loads_json(skill.effect_operations_json, [])
        if operations in (None, []):
            return []
        if not isinstance(operations, list):
            return [
                {
                    "status": "skipped",
                    "reason": "effect_operations_json_not_list",
                    "skill_id": battle_event.skill_id,
                }
            ]

        return self.execute_operations_for_event(
            battle_event,
            [
                item
                for item in operations
                if isinstance(item, dict) and item.get("timing") != "after_damage"
            ],
        )

    def execute_for_damage_event(self, battle_event: BattleEvent) -> list[dict]:
        """执行明确标记为 after_damage 的技能后置效果。"""
        if battle_event.skill_id is None:
            return []
        skill = self.db.get(SkillDefinition, battle_event.skill_id)
        if skill is None or skill.deleted_at is not None:
            return []
        operations = loads_json(skill.effect_operations_json, [])
        if not isinstance(operations, list):
            return []
        return self.execute_operations_for_event(
            battle_event,
            [
                item
                for item in operations
                if isinstance(item, dict) and item.get("timing") == "after_damage"
            ],
        )

    def execute_operations_for_event(
        self,
        battle_event: BattleEvent,
        operations: list[dict],
    ) -> list[dict]:
        """执行调用方显式传入的一组结构化效果操作。"""
        results: list[dict] = []
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                results.append(
                    {
                        "status": "skipped",
                        "reason": "operation_not_object",
                        "operation_index": index,
                    }
                )
                continue
            results.append(self._execute_operation(battle_event, operation, index))
        return results

    def _execute_operation(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """执行单条操作。"""
        operation_type = (
            operation.get("operation")
            or operation.get("op_type")
            or operation.get("type")
        )
        if operation_type not in self.SUPPORTED_OPERATIONS:
            return self._skipped(operation, operation_index, "unsupported_operation")

        timing = operation.get("timing")
        if timing not in (None, "", "on_skill_use", "after_damage_or_skill_use", "after_damage"):
            return self._skipped(operation, operation_index, "unsupported_timing")

        condition = operation.get("condition")
        condition_result = self._condition_result(battle_event, condition)
        if condition_result != "matched":
            return {
                "status": "unknown" if condition_result == "unknown" else "skipped",
                "reason": condition_result,
                "operation_index": operation_index,
                "operation": operation_type,
                "condition": condition,
                "effect_id": operation.get("effect_id"),
            }

        if operation_type == "conditional_branch":
            return self._execute_conditional_branch(battle_event, operation, operation_index)
        if operation_type == "modify_skill_slots":
            return self._execute_modify_skill_slots(battle_event, operation, operation_index)
        if operation_type == "prepare_next_switch_in_effect":
            return self._execute_prepare_next_switch_in_effect(
                battle_event,
                operation,
                operation_index,
            )
        if operation_type == "interrupt_action":
            return self._execute_interrupt_action(battle_event, operation, operation_index)
        if operation_type == "resource_change":
            return self._execute_resource_change(battle_event, operation, operation_index)
        if operation_type == "resource_change_multi_target":
            return self._execute_resource_change_multi_target(
                battle_event,
                operation,
                operation_index,
            )
        if operation_type == "resource_change_from_effect_layers":
            return self._execute_resource_change_from_effect_layers(
                battle_event,
                operation,
                operation_index,
            )
        if operation_type == "heal_from_damage_dealt":
            return self._execute_heal_from_damage_dealt(battle_event, operation, operation_index)
        if operation_type == "convert_effect":
            return self._execute_convert_effect(battle_event, operation, operation_index)
        if operation_type == "convert_effects_by_polarity":
            return self._execute_convert_effects_by_polarity(
                battle_event,
                operation,
                operation_index,
            )
        if operation_type == "swap_hp_percent":
            return self._execute_swap_hp_percent(battle_event, operation, operation_index)
        if operation_type == "trigger_status_damage_now":
            return self._execute_trigger_status_damage_now(
                battle_event,
                operation,
                operation_index,
            )
        if operation_type == "clear_effects":
            return self._execute_clear_effects(battle_event, operation, operation_index)
        if operation_type == "clear_effect_layers":
            return self._execute_clear_effect_layers(battle_event, operation, operation_index)
        if operation_type == "multiply_layers_by_polarity":
            return self._execute_multiply_layers_by_polarity(
                battle_event,
                operation,
                operation_index,
                condition,
            )

        effect_id = operation.get("effect_id")
        if not isinstance(effect_id, str) or not effect_id:
            return self._skipped(operation, operation_index, "effect_id_missing")
        definition = self.db.get(EffectDefinition, effect_id)
        if definition is None or definition.deleted_at is not None:
            return self._skipped(operation, operation_index, "effect_definition_missing")

        if operation_type == "change_weather":
            return self._execute_change_weather(
                battle_event,
                operation,
                operation_index,
                definition,
            )

        target = self._resolve_target(battle_event, operation.get("target"), definition)
        if target["status"] != "resolved":
            return {
                "status": "skipped",
                "reason": target["reason"],
                "operation_index": operation_index,
                "operation": operation_type,
                "effect_id": effect_id,
            }

        if operation_type == "remove_effect":
            return self._execute_remove_effect(
                battle_event,
                operation,
                operation_index,
                definition,
                target,
            )
        if operation_type == "multiply_layers":
            return self._execute_multiply_layers(
                battle_event,
                operation,
                operation_index,
                definition,
                target,
                condition,
            )

        layers_result = self._resolve_layers(battle_event, operation, definition, target)
        if layers_result["status"] != "resolved":
            return {
                "status": "unknown" if layers_result["status"] == "unknown" else "skipped",
                "reason": layers_result["reason"],
                "operation_index": operation_index,
                "operation": operation_type,
                "effect_id": effect_id,
            }
        layers = int(layers_result["layers"])
        layer_bonus_sources = self._positive_stat_layer_bonus_sources(
            battle_event,
            definition,
            target,
        )
        if layer_bonus_sources:
            layers += sum(int(item["layers_bonus"]) for item in layer_bonus_sources)
            if definition.max_layers is not None:
                layers = min(layers, definition.max_layers)
        existing = self._find_existing_instance(
            battle_id=battle_event.battle_id,
            definition=definition,
            owner_side=target.get("owner_side"),
            owner_elf_id=target.get("owner_elf_id"),
            owner_skill_slot_id=target.get("owner_skill_slot_id"),
            field_id=target.get("field_id"),
        )
        if existing is None:
            instance = self._create_instance(
                battle_event=battle_event,
                definition=definition,
                target=target,
                layers=layers,
                operation=operation,
            )
            change_type = "apply"
            layers_before = None
        else:
            instance = existing
            layers_before = existing.layers
            self._update_existing_instance(
                instance=existing,
                definition=definition,
                layers=layers,
                turn_number=battle_event.turn_number,
                operation=operation,
            )
            change_type = "stack" if definition.stack_rule in {"add", "add_layers"} else "refresh"

        self.db.flush()
        self._create_effect_change_event(
            battle_event=battle_event,
            definition=definition,
            instance=instance,
            change_type=change_type,
            layers_before=layers_before,
            condition_branch=str(condition) if condition not in self.ALWAYS_CONDITIONS else None,
            reason="skill_effect_operation",
        )
        return {
            "status": "executed",
            "operation_index": operation_index,
            "operation": operation_type,
            "effect_id": definition.effect_id,
            "effect_name": definition.effect_name,
            "effect_instance_id": instance.instance_id,
            "target": operation.get("target"),
            "owner_scope": instance.owner_scope,
            "owner_side": instance.owner_side,
            "owner_elf_id": instance.owner_elf_id,
            "layers_before": layers_before,
            "layers_after": instance.layers,
            "layer_bonus_sources": layer_bonus_sources,
            "layers_resolution": self._layers_resolution_detail(layers_result),
        }

    def _positive_stat_layer_bonus_sources(
        self,
        battle_event: BattleEvent,
        definition: EffectDefinition,
        target: dict,
    ) -> list[dict]:
        """解析“获得属性增益时额外加层”的监听来源。

        当前落地已确认的萌芽印记口径：新获得的属性/技能增益额外 +1 层；
        不作用于印记、天气、技能槽增益等非可叠层增益。
        """
        if not self._eligible_for_positive_stat_layer_bonus(definition):
            return []
        target_side = target.get("owner_side")
        if target_side not in {Side.SELF.value, Side.ENEMY.value}:
            return []
        marks = self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle_event.battle_id,
                BattleEffectInstance.effect_id == "effect_cute_mark",
                BattleEffectInstance.owner_scope == OwnerScope.SIDE.value,
                BattleEffectInstance.owner_side == target_side,
                BattleEffectInstance.is_active.is_(True),
            )
        ).all()
        if not marks:
            return []
        # 用户确认：萌化印记让“新获得的那个增益多 +1 层”，不是按印记层数累加。
        source = marks[0]
        return [
            {
                "effect_id": source.effect_id,
                "effect_instance_id": source.instance_id,
                "layers_bonus": 1,
                "reason": "cute_mark_positive_stat_bonus",
            }
        ]

    @staticmethod
    def _eligible_for_positive_stat_layer_bonus(definition: EffectDefinition) -> bool:
        if definition.polarity != "positive":
            return False
        if definition.category not in {"stat_modifier", "skill_modifier"}:
            return False
        if definition.owner_scope == OwnerScope.SKILL_SLOT.value:
            return False
        if definition.attach_target_type == "skill_slot":
            return False
        return True

    def _execute_conditional_branch(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """执行条件分支中的子操作。"""
        child_operations = operation.get("operations")
        if not isinstance(child_operations, list):
            return self._skipped(operation, operation_index, "branch_operations_not_list")
        child_results: list[dict] = []
        for child_index, child_operation in enumerate(child_operations):
            if not isinstance(child_operation, dict):
                child_results.append(
                    {
                        "status": "skipped",
                        "reason": "operation_not_object",
                        "operation_index": child_index,
                    }
                )
                continue
            child_results.append(
                self._execute_operation(
                    battle_event,
                    child_operation,
                    child_index,
                )
            )
        return {
            "status": "executed",
            "operation_index": operation_index,
            "operation": "conditional_branch",
            "child_results": child_results,
        }

    def _execute_prepare_next_switch_in_effect(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """把“下一次切换入场”待执行效果记录到技能事件 payload。"""
        if battle_event.actor_side is None or battle_event.actor_elf_id is None:
            return self._skipped(operation, operation_index, "actor_missing")
        effect_type = str(operation.get("effect_type") or "")
        if effect_type not in {"inherit_positive_elf_effects", "resource_change", "force_switch"}:
            return self._skipped(operation, operation_index, "unsupported_pending_switch_effect")
        item = {
            "effect_type": effect_type,
            "source_skill_id": battle_event.skill_id,
            "source_event_id": battle_event.event_id,
            "source_side": battle_event.actor_side,
            "source_elf_id": battle_event.actor_elf_id,
            "target": operation.get("target") or "actor_side",
        }
        for key in (
            "resource_type",
            "change_type",
            "value",
            "value_type",
            "max_value",
            "switch_mode",
        ):
            if key in operation:
                item[key] = operation[key]
        payload = loads_json(battle_event.payload_json, {})
        if not isinstance(payload, dict):
            payload = {}
        pending = payload.get("pending_next_switch_in")
        if not isinstance(pending, list):
            pending = []
        pending.append(item)
        payload["pending_next_switch_in"] = pending
        battle_event.payload_json = dumps_json(payload)
        return {
            "status": "executed",
            "operation_index": operation_index,
            "operation": "prepare_next_switch_in_effect",
            **item,
        }

    def _execute_interrupt_action(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """记录“打断被应对技能”的结构化结果。

        当前系统仍以手动事件流为准，不会删除用户已经录入的后续事件；这里把打断
        写回 payload，供前端和后续重放逻辑识别该技能分支已经触发。
        """
        payload = loads_json(battle_event.payload_json, {})
        if not isinstance(payload, dict):
            payload = {}
        interrupted = payload.get("interrupted_actions")
        if not isinstance(interrupted, list):
            interrupted = []
        item = {
            "source_skill_id": battle_event.skill_id,
            "target": operation.get("target") or "responded_skill",
            "reason": operation.get("reason") or "skill_interrupt_action",
        }
        interrupted.append(item)
        payload["interrupted_actions"] = interrupted
        battle_event.payload_json = dumps_json(payload)
        return {
            "status": "executed",
            "operation_index": operation_index,
            "operation": "interrupt_action",
            **item,
        }

    def _execute_modify_skill_slots(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """批量调整运行时技能槽字段，目前用于防御技能冷却修正。"""
        target_side = self._resolve_target_side(battle_event, operation.get("target"))
        if target_side is None:
            return self._skipped(operation, operation_index, "target_side_missing")
        battle = self.db.get(Battle, battle_event.battle_id)
        if battle is None or battle.deleted_at is not None:
            return self._skipped(operation, operation_index, "battle_missing")
        target_elf_id = self._resolve_target_elf_id(battle, battle_event, target_side)
        if target_elf_id is None:
            return self._skipped(operation, operation_index, "target_elf_id_missing")
        slots = self.db.scalars(
            select(BattleSkillSlot).where(
                BattleSkillSlot.battle_id == battle_event.battle_id,
                BattleSkillSlot.side == target_side,
                BattleSkillSlot.elf_id == target_elf_id,
            )
        ).all()
        skill_category = operation.get("skill_category")
        slot_kind = operation.get("slot_kind")
        cooldown_delta = int(operation.get("cooldown_delta") or 0)
        changed: list[dict] = []
        for slot in slots:
            skill = self.db.get(SkillDefinition, slot.skill_id)
            if skill is None or skill.deleted_at is not None:
                continue
            if skill_category is not None and skill.skill_category != str(skill_category):
                continue
            if slot_kind == "defense" and not self._skill_has_defense_rule(skill):
                continue
            before_cooldown = slot.cooldown_remaining or 0
            if cooldown_delta:
                slot.cooldown_remaining = max(before_cooldown + cooldown_delta, 0)
            changed.append(
                {
                    "slot_id": slot.slot_id,
                    "skill_id": slot.skill_id,
                    "skill_name": skill.skill_name,
                    "cooldown_before": before_cooldown,
                    "cooldown_after": slot.cooldown_remaining,
                }
            )
        return {
            "status": "executed" if changed else "skipped",
            "reason": None if changed else "no_matching_skill_slots",
            "operation_index": operation_index,
            "operation": "modify_skill_slots",
            "target_side": target_side,
            "target_elf_id": target_elf_id,
            "changed": changed,
        }

    @staticmethod
    def _skill_has_defense_rule(skill: SkillDefinition) -> bool:
        rule = loads_json(skill.damage_rule_json, {})
        if not isinstance(rule, dict):
            return False
        return any(
            rule.get(key) is not None
            for key in ("damage_reduction", "reduction", "damage_multiplier", "multiplier")
        )

    def _execute_change_weather(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
        definition: EffectDefinition,
    ) -> dict:
        """切换天气：先清除同 conflict_group 的旧天气，再施加新天气。"""
        if definition.owner_scope != OwnerScope.FIELD.value:
            return self._skipped(operation, operation_index, "weather_effect_not_field_scope")
        removed = self._clear_matching_effects(
            battle_event=battle_event,
            operation=operation,
            effect_ids=None,
            categories={"weather"},
            polarity=None,
            conflict_group=definition.conflict_group or "weather",
            exclude_effect_id=definition.effect_id,
            reason="change_weather_replace",
        )
        target = self._resolve_target(battle_event, "field", definition)
        if target["status"] != "resolved":
            return self._skipped(operation, operation_index, target["reason"])
        layers_result = self._resolve_layers(battle_event, operation, definition, target)
        if layers_result["status"] != "resolved":
            return {
                "status": "unknown",
                "reason": layers_result["reason"],
                "operation_index": operation_index,
                "operation": "change_weather",
                "effect_id": definition.effect_id,
            }
        instance = self._find_existing_instance(
            battle_id=battle_event.battle_id,
            definition=definition,
            owner_side=None,
            owner_elf_id=None,
            owner_skill_slot_id=None,
            field_id=target.get("field_id"),
        )
        layers_before = instance.layers if instance is not None else None
        if instance is None:
            instance = self._create_instance(
                battle_event=battle_event,
                definition=definition,
                target=target,
                layers=int(layers_result["layers"]),
                operation=operation,
            )
            change_type = "weather_change"
        else:
            self._update_existing_instance(
                instance=instance,
                definition=definition,
                layers=int(layers_result["layers"]),
                turn_number=battle_event.turn_number,
                operation=operation,
            )
            instance.is_active = True
            change_type = "weather_refresh"
        self.db.flush()
        self._create_effect_change_event(
            battle_event=battle_event,
            definition=definition,
            instance=instance,
            change_type=change_type,
            layers_before=layers_before,
            condition_branch=None,
            reason="change_weather",
        )
        return {
            "status": "executed",
            "operation_index": operation_index,
            "operation": "change_weather",
            "effect_id": definition.effect_id,
            "effect_instance_id": instance.instance_id,
            "removed_effects": removed,
            "layers_before": layers_before,
            "layers_after": instance.layers,
        }

    def _execute_remove_effect(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
        definition: EffectDefinition,
        target: dict,
    ) -> dict:
        """移除目标上的指定状态。"""
        existing = self._find_existing_instance(
            battle_id=battle_event.battle_id,
            definition=definition,
            owner_side=target.get("owner_side"),
            owner_elf_id=target.get("owner_elf_id"),
            owner_skill_slot_id=target.get("owner_skill_slot_id"),
            field_id=target.get("field_id"),
        )
        if existing is None:
            return {
                "status": "skipped",
                "reason": "effect_instance_missing",
                "operation_index": operation_index,
                "operation": "remove_effect",
                "effect_id": definition.effect_id,
            }
        layers_before = existing.layers
        existing.is_active = False
        existing.layers = 0
        existing.last_updated_turn = battle_event.turn_number
        self._create_effect_change_event(
            battle_event=battle_event,
            definition=definition,
            instance=existing,
            change_type="remove",
            layers_before=layers_before,
            condition_branch=None,
            reason="skill_remove_effect",
        )
        return {
            "status": "executed",
            "operation_index": operation_index,
            "operation": "remove_effect",
            "effect_id": definition.effect_id,
            "effect_instance_id": existing.instance_id,
            "layers_before": layers_before,
            "layers_after": 0,
        }

    def _execute_clear_effects(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """按 effect_ids/category/target 清除一组状态。"""
        effect_ids = self._normalize_str_set(operation.get("effect_ids"))
        categories = self._normalize_str_set(operation.get("categories"))
        polarity = str(operation.get("polarity") or "") or None
        if not effect_ids and isinstance(operation.get("effect_id"), str):
            effect_ids = {str(operation["effect_id"])}
        if not effect_ids and not categories and polarity is None:
            return self._skipped(operation, operation_index, "clear_selector_missing")
        removed = self._clear_matching_effects(
            battle_event=battle_event,
            operation=operation,
            effect_ids=effect_ids,
            categories=categories,
            polarity=polarity,
            conflict_group=None,
            exclude_effect_id=None,
            reason="skill_clear_effects",
        )
        return {
            "status": "executed" if removed else "skipped",
            "reason": None if removed else "no_matching_effects",
            "operation_index": operation_index,
            "operation": "clear_effects",
            "removed_effects": removed,
        }

    def _execute_multiply_layers(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
        definition: EffectDefinition,
        target: dict,
        condition: object,
    ) -> dict:
        """按倍率修改目标状态层数。"""
        existing = self._find_existing_instance(
            battle_id=battle_event.battle_id,
            definition=definition,
            owner_side=target.get("owner_side"),
            owner_elf_id=target.get("owner_elf_id"),
            owner_skill_slot_id=target.get("owner_skill_slot_id"),
            field_id=target.get("field_id"),
        )
        if existing is None:
            return self._skipped(operation, operation_index, "effect_instance_missing")
        multiplier = operation.get("multiplier")
        if not isinstance(multiplier, int | float) or multiplier <= 0:
            return self._skipped(operation, operation_index, "invalid_multiplier")
        layers_before = existing.layers
        next_layers = int(existing.layers * multiplier)
        if definition.max_layers is not None:
            next_layers = min(next_layers, definition.max_layers)
        existing.layers = max(next_layers, 0)
        existing.is_active = existing.layers > 0
        existing.last_updated_turn = battle_event.turn_number
        self._create_effect_change_event(
            battle_event=battle_event,
            definition=definition,
            instance=existing,
            change_type="multiply_layers",
            layers_before=layers_before,
            condition_branch=str(condition) if condition not in self.ALWAYS_CONDITIONS else None,
            reason="skill_multiply_layers",
        )
        return {
            "status": "executed",
            "operation_index": operation_index,
            "operation": "multiply_layers",
            "effect_id": definition.effect_id,
            "effect_instance_id": existing.instance_id,
            "multiplier": multiplier,
            "layers_before": layers_before,
            "layers_after": existing.layers,
        }

    def _execute_clear_effect_layers(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """按玩家指定的状态实例扣除层数，不自动选择目标。"""
        selections = operation.get("selected_effect_instance_layers")
        if selections is None:
            payload = loads_json(battle_event.payload_json, {})
            if isinstance(payload, dict):
                selections = payload.get("selected_effect_instance_layers")
        if not isinstance(selections, list) or not selections:
            return {
                "status": "unknown",
                "reason": "manual_layer_selection_missing",
                "operation_index": operation_index,
                "operation": "clear_effect_layers",
            }

        target_side = self._resolve_target_side(battle_event, operation.get("target"))
        definitions_by_id = self._load_effect_definitions()
        changed: list[dict] = []
        skipped: list[dict] = []
        for index, selection in enumerate(selections):
            if not isinstance(selection, dict):
                skipped.append({"index": index, "reason": "selection_not_object"})
                continue
            instance_id = selection.get("instance_id") or selection.get("effect_instance_id")
            raw_layers = selection.get("layers")
            if not isinstance(instance_id, str) or not instance_id:
                skipped.append({"index": index, "reason": "effect_instance_id_missing"})
                continue
            if not isinstance(raw_layers, int | float) or int(raw_layers) <= 0:
                skipped.append(
                    {"index": index, "instance_id": instance_id, "reason": "layers_invalid"}
                )
                continue
            instance = self.db.get(BattleEffectInstance, instance_id)
            if (
                instance is None
                or instance.battle_id != battle_event.battle_id
                or not instance.is_active
            ):
                skipped.append(
                    {
                        "index": index,
                        "instance_id": instance_id,
                        "reason": "active_instance_missing",
                    }
                )
                continue
            definition = definitions_by_id.get(instance.effect_id)
            if definition is None:
                skipped.append(
                    {
                        "index": index,
                        "instance_id": instance_id,
                        "reason": "effect_definition_missing",
                    }
                )
                continue
            if target_side is not None and instance.owner_scope != OwnerScope.FIELD.value:
                if instance.owner_side != target_side:
                    skipped.append(
                        {
                            "index": index,
                            "instance_id": instance_id,
                            "reason": "target_side_mismatch",
                        }
                    )
                    continue

            layers_before = instance.layers
            clear_layers = min(int(raw_layers), max(instance.layers, 0))
            instance.layers = max(instance.layers - clear_layers, 0)
            instance.is_active = instance.layers > 0
            instance.last_updated_turn = battle_event.turn_number
            self._create_effect_change_event(
                battle_event=battle_event,
                definition=definition,
                instance=instance,
                change_type="clear_layers" if instance.is_active else "clear",
                layers_before=layers_before,
                condition_branch=None,
                reason="manual_clear_effect_layers",
            )
            changed.append(
                {
                    "effect_id": instance.effect_id,
                    "effect_instance_id": instance.instance_id,
                    "requested_layers": int(raw_layers),
                    "cleared_layers": clear_layers,
                    "layers_before": layers_before,
                    "layers_after": instance.layers,
                }
            )
        return {
            "status": "executed" if changed else "skipped",
            "reason": None if changed else "no_layers_cleared",
            "operation_index": operation_index,
            "operation": "clear_effect_layers",
            "changed_effects": changed,
            "skipped_selections": skipped,
        }

    def _execute_multiply_layers_by_polarity(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
        condition: object,
    ) -> dict:
        """按极性批量修改目标状态层数，用于“增益翻倍”等机制。"""
        polarity = str(operation.get("polarity") or "")
        if polarity not in {"positive", "negative", "neutral"}:
            return self._skipped(operation, operation_index, "invalid_polarity")
        multiplier = operation.get("multiplier", 2)
        if not isinstance(multiplier, int | float) or multiplier <= 0:
            return self._skipped(operation, operation_index, "invalid_multiplier")
        target_side = self._resolve_target_side(battle_event, operation.get("target"))
        definitions_by_id = self._load_effect_definitions()
        changed: list[dict] = []
        for instance in self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle_event.battle_id,
                BattleEffectInstance.is_active.is_(True),
            )
        ).all():
            definition = definitions_by_id.get(instance.effect_id)
            if definition is None or definition.polarity != polarity:
                continue
            if target_side is not None and instance.owner_scope != OwnerScope.FIELD.value:
                if instance.owner_side != target_side:
                    continue
            layers_before = instance.layers
            next_layers = int(instance.layers * multiplier)
            if definition.max_layers is not None:
                next_layers = min(next_layers, definition.max_layers)
            instance.layers = max(next_layers, 0)
            instance.is_active = instance.layers > 0
            instance.last_updated_turn = battle_event.turn_number
            self._create_effect_change_event(
                battle_event=battle_event,
                definition=definition,
                instance=instance,
                change_type="multiply_layers",
                layers_before=layers_before,
                condition_branch=(
                    str(condition) if condition not in self.ALWAYS_CONDITIONS else None
                ),
                reason="skill_multiply_layers_by_polarity",
            )
            changed.append(
                {
                    "effect_id": instance.effect_id,
                    "effect_instance_id": instance.instance_id,
                    "polarity": polarity,
                    "multiplier": multiplier,
                    "layers_before": layers_before,
                    "layers_after": instance.layers,
                }
            )
        return {
            "status": "executed" if changed else "skipped",
            "reason": None if changed else "no_matching_effects",
            "operation_index": operation_index,
            "operation": "multiply_layers_by_polarity",
            "changed_effects": changed,
        }

    def _execute_heal_from_damage_dealt(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """按本次已知伤害量回复生命，回复值向下取整。"""
        damage_value = self._damage_value_from_event_payload(battle_event, operation)
        if damage_value is None:
            return {
                "status": "unknown",
                "reason": "damage_value_missing",
                "operation_index": operation_index,
                "operation": "heal_from_damage_dealt",
            }
        ratio = operation.get("ratio", 1)
        if not isinstance(ratio, int | float) or ratio < 0:
            return self._skipped(operation, operation_index, "invalid_ratio")
        heal_value = floor(float(damage_value) * float(ratio))
        heal_operation = dict(operation)
        heal_operation.update(
            {
                "op_type": "resource_change",
                "resource_type": "hp",
                "change_type": "heal",
                "value_type": "value",
                "value": heal_value,
            }
        )
        result = self._execute_resource_change(battle_event, heal_operation, operation_index)
        result["operation"] = "heal_from_damage_dealt"
        result["damage_value"] = damage_value
        result["ratio"] = ratio
        result["heal_value"] = heal_value
        result["rounding"] = "floor"
        return result

    def _execute_convert_effect(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """把目标身上的一种状态转换为另一种状态，层数默认继承。"""
        from_effect_id = operation.get("from_effect_id") or operation.get("source_effect_id")
        to_effect_id = operation.get("to_effect_id") or operation.get("effect_id")
        if not isinstance(from_effect_id, str) or not from_effect_id:
            return self._skipped(operation, operation_index, "from_effect_id_missing")
        if not isinstance(to_effect_id, str) or not to_effect_id:
            return self._skipped(operation, operation_index, "to_effect_id_missing")
        from_definition = self.db.get(EffectDefinition, from_effect_id)
        to_definition = self.db.get(EffectDefinition, to_effect_id)
        if from_definition is None or from_definition.deleted_at is not None:
            return self._skipped(operation, operation_index, "from_effect_definition_missing")
        if to_definition is None or to_definition.deleted_at is not None:
            return self._skipped(operation, operation_index, "to_effect_definition_missing")

        target = self._resolve_target(
            battle_event,
            operation.get("target"),
            from_definition,
        )
        if target["status"] != "resolved":
            return self._skipped(operation, operation_index, target["reason"])
        existing = self._find_existing_instance(
            battle_id=battle_event.battle_id,
            definition=from_definition,
            owner_side=target.get("owner_side"),
            owner_elf_id=target.get("owner_elf_id"),
            owner_skill_slot_id=target.get("owner_skill_slot_id"),
            field_id=target.get("field_id"),
        )
        if existing is None or not existing.is_active or existing.layers <= 0:
            return self._skipped(operation, operation_index, "source_effect_instance_missing")

        layers_before = existing.layers
        existing.is_active = False
        existing.layers = 0
        existing.last_updated_turn = battle_event.turn_number
        self._create_effect_change_event(
            battle_event=battle_event,
            definition=from_definition,
            instance=existing,
            change_type="convert",
            layers_before=layers_before,
            condition_branch=str(operation.get("condition") or "") or None,
            reason="skill_convert_effect_source",
        )

        apply_operation = dict(operation)
        apply_operation.update(
            {
                "op_type": "apply_effect",
                "effect_id": to_effect_id,
                "layers": layers_before,
                "target": operation.get("target"),
                "condition": "always",
            }
        )
        target_to = self._resolve_target(battle_event, operation.get("target"), to_definition)
        if target_to["status"] != "resolved":
            return self._skipped(operation, operation_index, target_to["reason"])
        instance = self._find_existing_instance(
            battle_id=battle_event.battle_id,
            definition=to_definition,
            owner_side=target_to.get("owner_side"),
            owner_elf_id=target_to.get("owner_elf_id"),
            owner_skill_slot_id=target_to.get("owner_skill_slot_id"),
            field_id=target_to.get("field_id"),
        )
        layers_to_apply = layers_before
        if to_definition.max_layers is not None:
            layers_to_apply = min(layers_to_apply, to_definition.max_layers)
        if instance is None:
            instance = self._create_instance(
                battle_event=battle_event,
                definition=to_definition,
                target=target_to,
                layers=layers_to_apply,
                operation=apply_operation,
            )
            target_layers_before = None
            change_type = "apply"
        else:
            target_layers_before = instance.layers
            self._update_existing_instance(
                instance=instance,
                definition=to_definition,
                layers=layers_to_apply,
                turn_number=battle_event.turn_number,
                operation=apply_operation,
            )
            instance.is_active = True
            change_type = "stack"
        self._create_effect_change_event(
            battle_event=battle_event,
            definition=to_definition,
            instance=instance,
            change_type=change_type,
            layers_before=target_layers_before,
            condition_branch=str(operation.get("condition") or "") or None,
            reason="skill_convert_effect_target",
        )
        return {
            "status": "executed",
            "operation_index": operation_index,
            "operation": "convert_effect",
            "from_effect_id": from_effect_id,
            "to_effect_id": to_effect_id,
            "converted_layers": layers_before,
            "source_effect_instance_id": existing.instance_id,
            "target_effect_instance_id": instance.instance_id,
        }

    def _execute_convert_effects_by_polarity(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """把目标当前精灵身上指定极性的状态转换为目标状态，层数按总层数继承。"""
        from_polarity = str(operation.get("from_polarity") or "")
        if from_polarity not in {"positive", "negative", "neutral"}:
            return self._skipped(operation, operation_index, "invalid_from_polarity")
        to_effect_id = operation.get("to_effect_id") or operation.get("effect_id")
        if not isinstance(to_effect_id, str) or not to_effect_id:
            return self._skipped(operation, operation_index, "to_effect_id_missing")
        to_definition = self.db.get(EffectDefinition, to_effect_id)
        if to_definition is None or to_definition.deleted_at is not None:
            return self._skipped(operation, operation_index, "to_effect_definition_missing")

        battle = self.db.get(Battle, battle_event.battle_id)
        target_side = self._resolve_target_side(battle_event, operation.get("target"))
        if battle is None or battle.deleted_at is not None or target_side is None:
            return self._skipped(operation, operation_index, "target_side_missing")
        target_elf_id = self._resolve_target_elf_id(battle, battle_event, target_side)
        if target_elf_id is None:
            return self._skipped(operation, operation_index, "target_elf_id_missing")

        definitions_by_id = self._load_effect_definitions()
        converted_layers = 0
        removed: list[dict] = []
        for instance in self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle_event.battle_id,
                BattleEffectInstance.owner_scope == OwnerScope.ELF.value,
                BattleEffectInstance.owner_side == target_side,
                BattleEffectInstance.owner_elf_id == target_elf_id,
                BattleEffectInstance.is_active.is_(True),
            )
        ).all():
            definition = definitions_by_id.get(instance.effect_id)
            if definition is None or definition.polarity != from_polarity:
                continue
            if instance.effect_id == to_effect_id:
                continue
            layers_before = max(int(instance.layers or 0), 0)
            if layers_before <= 0:
                continue
            converted_layers += layers_before
            instance.is_active = False
            instance.layers = 0
            instance.last_updated_turn = battle_event.turn_number
            self._create_effect_change_event(
                battle_event=battle_event,
                definition=definition,
                instance=instance,
                change_type="convert",
                layers_before=layers_before,
                condition_branch=str(operation.get("condition") or "") or None,
                reason="skill_convert_effects_by_polarity_source",
            )
            removed.append(
                {
                    "effect_id": instance.effect_id,
                    "effect_instance_id": instance.instance_id,
                    "layers_before": layers_before,
                    "layers_after": 0,
                }
            )

        if converted_layers <= 0:
            return {
                "status": "skipped",
                "reason": "no_matching_effects",
                "operation_index": operation_index,
                "operation": "convert_effects_by_polarity",
                "from_polarity": from_polarity,
                "to_effect_id": to_effect_id,
                "target_side": target_side,
                "target_elf_id": target_elf_id,
            }

        apply_operation = dict(operation)
        apply_operation.update(
            {
                "op_type": "apply_effect",
                "effect_id": to_effect_id,
                "target": operation.get("target"),
                "layers": converted_layers,
                "condition": "always",
            }
        )
        target = self._resolve_target(battle_event, operation.get("target"), to_definition)
        if target["status"] != "resolved":
            return self._skipped(operation, operation_index, target["reason"])
        target_layers_before = None
        target_instance = self._find_existing_instance(
            battle_id=battle_event.battle_id,
            definition=to_definition,
            owner_side=target.get("owner_side"),
            owner_elf_id=target.get("owner_elf_id"),
            owner_skill_slot_id=target.get("owner_skill_slot_id"),
            field_id=target.get("field_id"),
        )
        layers_to_apply = converted_layers
        if to_definition.max_layers is not None:
            layers_to_apply = min(layers_to_apply, to_definition.max_layers)
        if target_instance is None:
            target_instance = self._create_instance(
                battle_event=battle_event,
                definition=to_definition,
                target=target,
                layers=layers_to_apply,
                operation=apply_operation,
            )
            change_type = "apply"
        else:
            target_layers_before = target_instance.layers
            self._update_existing_instance(
                instance=target_instance,
                definition=to_definition,
                layers=layers_to_apply,
                turn_number=battle_event.turn_number,
                operation=apply_operation,
            )
            target_instance.is_active = True
            change_type = "stack"
        self._create_effect_change_event(
            battle_event=battle_event,
            definition=to_definition,
            instance=target_instance,
            change_type=change_type,
            layers_before=target_layers_before,
            condition_branch=str(operation.get("condition") or "") or None,
            reason="skill_convert_effects_by_polarity_target",
        )
        return {
            "status": "executed",
            "operation_index": operation_index,
            "operation": "convert_effects_by_polarity",
            "from_polarity": from_polarity,
            "to_effect_id": to_effect_id,
            "converted_layers": converted_layers,
            "target_side": target_side,
            "target_elf_id": target_elf_id,
            "removed_effects": removed,
            "target_effect_instance_id": target_instance.instance_id,
        }

    def _execute_swap_hp_percent(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """交换行动方与目标的当前生命比例；结果不会把任一方置为 0 HP。"""
        actor_state = self._resolve_resource_target(battle_event, "actor_side")
        target_state = self._resolve_resource_target(battle_event, operation.get("target"))
        if actor_state is None or target_state is None:
            return self._skipped(operation, operation_index, "resource_target_missing")
        actor_max_hp = self._max_hp(actor_state)
        target_max_hp = self._max_hp(target_state)
        if actor_max_hp is None or target_max_hp is None:
            return self._skipped(operation, operation_index, "max_hp_missing")

        actor_percent = self._current_hp_percent(actor_state, actor_max_hp)
        target_percent = self._current_hp_percent(target_state, target_max_hp)
        actor_before = actor_state.current_hp_value
        target_before = target_state.current_hp_value
        actor_state.current_hp_value = self._hp_from_percent(actor_max_hp, target_percent)
        actor_state.current_hp_percent = round(target_percent, 4)
        actor_state.is_defeated = False
        target_state.current_hp_value = self._hp_from_percent(target_max_hp, actor_percent)
        target_state.current_hp_percent = round(actor_percent, 4)
        target_state.is_defeated = False
        events = [
            self._add_resource_event_for_state(
                battle_event=battle_event,
                state=actor_state,
                resource_type="hp",
                change_type="swap_percent",
                value=target_percent,
                before_value=actor_before,
                after_value=actor_state.current_hp_value,
                value_type="percent",
            ),
            self._add_resource_event_for_state(
                battle_event=battle_event,
                state=target_state,
                resource_type="hp",
                change_type="swap_percent",
                value=actor_percent,
                before_value=target_before,
                after_value=target_state.current_hp_value,
                value_type="percent",
            ),
        ]
        return {
            "status": "executed",
            "operation_index": operation_index,
            "operation": "swap_hp_percent",
            "actor_side": actor_state.side,
            "actor_elf_id": actor_state.elf_id,
            "target_side": target_state.side,
            "target_elf_id": target_state.elf_id,
            "actor_percent_before": actor_percent,
            "target_percent_before": target_percent,
            "actor_hp_before": actor_before,
            "actor_hp_after": actor_state.current_hp_value,
            "target_hp_before": target_before,
            "target_hp_after": target_state.current_hp_value,
            "resource_event_ids": [event.event_id for event in events],
        }

    def _execute_trigger_status_damage_now(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """立即结算目标身上指定状态的一次状态伤害。"""
        effect_id = operation.get("effect_id") or operation.get("source_effect_id")
        if not isinstance(effect_id, str) or not effect_id:
            return self._skipped(operation, operation_index, "effect_id_missing")
        definition = self.db.get(EffectDefinition, effect_id)
        if definition is None or definition.deleted_at is not None:
            return self._skipped(operation, operation_index, "effect_definition_missing")
        target = self._resolve_target(battle_event, operation.get("target"), definition)
        if target["status"] != "resolved":
            return self._skipped(operation, operation_index, target["reason"])
        instance = self._find_existing_instance(
            battle_id=battle_event.battle_id,
            definition=definition,
            owner_side=target.get("owner_side"),
            owner_elf_id=target.get("owner_elf_id"),
            owner_skill_slot_id=target.get("owner_skill_slot_id"),
            field_id=target.get("field_id"),
        )
        if instance is None or not instance.is_active or instance.layers <= 0:
            return self._skipped(operation, operation_index, "effect_instance_missing")
        battle = self.db.get(Battle, battle_event.battle_id)
        if battle is None or battle.deleted_at is not None:
            return self._skipped(operation, operation_index, "battle_missing")
        resource_rule = loads_json(definition.resource_modifier_json, {})
        if not isinstance(resource_rule, dict) or not resource_rule:
            return self._skipped(operation, operation_index, "resource_rule_missing")

        from app.services.turn_settlement_service import TurnSettlementService

        result = TurnSettlementService(self.db)._settle_status_damage(
            battle=battle,
            turn_number=battle_event.turn_number,
            instance=instance,
            definition=definition,
            resource_rule=resource_rule,
            settlement_phase=str(operation.get("settlement_phase") or "skill_triggered"),
        )
        settled = result.get("status") in {"settled", "settled_percent"}
        return {
            "status": "executed" if settled else "skipped",
            "reason": None if settled else result.get("reason"),
            "operation_index": operation_index,
            "operation": "trigger_status_damage_now",
            "effect_id": effect_id,
            "settlement_result": result,
        }

    def _execute_resource_change(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """执行生命/能量资源变化，并写入 ResourceChangeEvent。"""
        target_state = self._resolve_resource_target(battle_event, operation.get("target"))
        if target_state is None:
            return self._skipped(operation, operation_index, "resource_target_missing")
        resource_type = str(operation.get("resource_type") or "hp")
        change_type = str(operation.get("change_type") or "manual_set")
        value_type = str(operation.get("value_type") or "value")
        raw_value = self._resolve_resource_change_value(battle_event, operation)
        if not isinstance(raw_value, int | float):
            return self._skipped(operation, operation_index, "resource_value_missing")

        before_value: float | int | None
        after_value: float | int | None
        if resource_type == "hp":
            before_value = target_state.current_hp_value
            after_value = self._apply_hp_resource_change(
                target_state,
                change_type,
                float(raw_value),
                value_type,
            )
        elif resource_type == "energy":
            before_value = target_state.energy
            after_value = self._apply_energy_resource_change(
                target_state,
                change_type,
                float(raw_value),
                max_value=self._optional_int(operation.get("max_value")),
            )
        else:
            return self._skipped(operation, operation_index, "unsupported_resource_type")

        self._add_resource_event_for_state(
            battle_event=battle_event,
            state=target_state,
            resource_type=resource_type,
            change_type=change_type,
            value=float(raw_value),
            value_type=value_type,
            before_value=before_value,
            after_value=after_value,
        )
        return {
            "status": "executed",
            "operation_index": operation_index,
            "operation": "resource_change",
            "resource_type": resource_type,
            "change_type": change_type,
            "target_side": target_state.side,
            "target_elf_id": target_state.elf_id,
            "value_type": value_type,
            "value": raw_value,
            "before_value": before_value,
            "after_value": after_value,
        }

    def _execute_resource_change_multi_target(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """对多只精灵执行同一种资源变化，目前用于场下队友回复能量。"""
        targets = self._resolve_resource_targets(battle_event, operation.get("target"))
        if not targets:
            return self._skipped(operation, operation_index, "resource_targets_missing")
        resource_type = str(operation.get("resource_type") or "energy")
        change_type = str(operation.get("change_type") or "gain")
        value_type = str(operation.get("value_type") or "value")
        raw_value = self._resolve_resource_change_value(battle_event, operation)
        if not isinstance(raw_value, int | float):
            return self._skipped(operation, operation_index, "resource_value_missing")

        changed: list[dict] = []
        for target_state in targets:
            if resource_type == "hp":
                before_value = target_state.current_hp_value
                after_value = self._apply_hp_resource_change(
                    target_state,
                    change_type,
                    float(raw_value),
                    value_type,
                )
            elif resource_type == "energy":
                before_value = target_state.energy
                after_value = self._apply_energy_resource_change(
                    target_state,
                    change_type,
                    float(raw_value),
                    max_value=self._optional_int(operation.get("max_value")),
                )
            else:
                continue
            event = self._add_resource_event_for_state(
                battle_event=battle_event,
                state=target_state,
                resource_type=resource_type,
                change_type=change_type,
                value=float(raw_value),
                value_type=value_type,
                before_value=before_value,
                after_value=after_value,
            )
            changed.append(
                {
                    "target_side": target_state.side,
                    "target_elf_id": target_state.elf_id,
                    "before_value": before_value,
                    "after_value": after_value,
                    "resource_event_id": event.event_id,
                }
            )

        return {
            "status": "executed" if changed else "skipped",
            "reason": None if changed else "no_supported_targets",
            "operation_index": operation_index,
            "operation": "resource_change_multi_target",
            "resource_type": resource_type,
            "change_type": change_type,
            "value_type": value_type,
            "value": raw_value,
            "target": operation.get("target"),
            "changed": changed,
        }

    def _execute_resource_change_from_effect_layers(
        self,
        battle_event: BattleEvent,
        operation: dict,
        operation_index: int,
    ) -> dict:
        """按指定目标当前状态层数执行资源变化。"""
        source_effect_id = operation.get("source_effect_id") or operation.get("effect_id")
        if not isinstance(source_effect_id, str) or not source_effect_id:
            return self._skipped(operation, operation_index, "source_effect_id_missing")
        source_definition = self.db.get(EffectDefinition, source_effect_id)
        if source_definition is None or source_definition.deleted_at is not None:
            return self._skipped(operation, operation_index, "source_effect_definition_missing")

        source_target = self._resolve_target(
            battle_event,
            operation.get("source_target") or operation.get("target"),
            source_definition,
        )
        if source_target["status"] != "resolved":
            return self._skipped(operation, operation_index, source_target["reason"])
        layer_result = self._sum_active_effect_layers(source_definition, source_target)
        if layer_result["layers"] <= 0:
            return {
                "status": "skipped",
                "reason": "source_effect_layers_zero",
                "operation_index": operation_index,
                "operation": "resource_change_from_effect_layers",
                "source_effect_id": source_effect_id,
                "source_target": operation.get("source_target"),
                "matched_instances": layer_result["matched_instances"],
            }

        value_per_layer = operation.get("value_per_layer", 1)
        if not isinstance(value_per_layer, int | float):
            return self._skipped(operation, operation_index, "value_per_layer_invalid")
        value = int(layer_result["layers"] * value_per_layer)
        if value <= 0:
            return self._skipped(operation, operation_index, "resource_value_zero")

        resource_operation = dict(operation)
        resource_operation.update(
            {
                "op_type": "resource_change",
                "value_type": "value",
                "value": value,
                "target": operation.get("target") or "actor_side",
            }
        )
        result = self._execute_resource_change(battle_event, resource_operation, operation_index)
        result.update(
            {
                "operation": "resource_change_from_effect_layers",
                "source_effect_id": source_effect_id,
                "source_target": operation.get("source_target"),
                "source_layers": layer_result["layers"],
                "value_per_layer": value_per_layer,
                "matched_instances": layer_result["matched_instances"],
            }
        )
        return result

    def _sum_active_effect_layers(
        self,
        definition: EffectDefinition,
        target: dict,
    ) -> dict:
        """汇总同一挂载目标上的 active 状态层数。"""
        stmt = select(BattleEffectInstance).where(
            BattleEffectInstance.battle_id == str(target.get("battle_id")),
            BattleEffectInstance.effect_id == definition.effect_id,
            BattleEffectInstance.owner_scope == definition.owner_scope,
            BattleEffectInstance.is_active.is_(True),
        )
        if definition.owner_scope == OwnerScope.FIELD.value:
            stmt = stmt.where(BattleEffectInstance.field_id == target.get("field_id"))
        else:
            stmt = stmt.where(BattleEffectInstance.owner_side == target.get("owner_side"))
            if definition.owner_scope == OwnerScope.ELF.value:
                stmt = stmt.where(BattleEffectInstance.owner_elf_id == target.get("owner_elf_id"))
            if definition.owner_scope == OwnerScope.SKILL_SLOT.value:
                stmt = stmt.where(
                    BattleEffectInstance.owner_skill_slot_id == target.get("owner_skill_slot_id")
                )
        instances = self.db.scalars(stmt).all()
        matched = [
            {
                "effect_instance_id": item.instance_id,
                "owner_scope": item.owner_scope,
                "owner_side": item.owner_side,
                "owner_elf_id": item.owner_elf_id,
                "owner_skill_slot_id": item.owner_skill_slot_id,
                "layers": item.layers,
            }
            for item in instances
        ]
        return {
            "layers": sum(max(int(item.layers or 0), 0) for item in instances),
            "matched_instances": matched,
        }

    @staticmethod
    def _damage_value_from_event_payload(
        battle_event: BattleEvent,
        operation: dict,
    ) -> float | int | None:
        payload = loads_json(battle_event.payload_json, {})
        if not isinstance(payload, dict):
            return None
        source = operation.get("damage_source")
        candidates = [source] if isinstance(source, str) and source else []
        candidates.extend(
            [
                "damage_value",
                "damage_dealt",
                "observed_damage",
                "computed_total_damage_value",
                "final_total_damage_value",
            ]
        )
        for key in candidates:
            value: object = payload
            for part in str(key).split("."):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            if isinstance(value, int | float):
                return value
        return None

    def _condition_result(self, battle_event: BattleEvent, condition: object) -> str:
        """判断条件分支是否满足；未知条件只返回 unknown。"""
        if condition in self.ALWAYS_CONDITIONS:
            return "matched"
        payload = loads_json(battle_event.payload_json, {})
        if not isinstance(payload, dict) or not isinstance(condition, str):
            return "unknown"
        if condition.startswith("not_"):
            positive = self._condition_result(battle_event, condition.removeprefix("not_"))
            if positive == "matched":
                return "condition_not_met"
            if positive == "condition_not_met":
                return "matched"
            return positive
        manual_flags = payload.get("manual_flags")
        condition_flags = payload.get("condition_flags")
        values = [
            payload.get(condition),
            manual_flags.get(condition) if isinstance(manual_flags, dict) else None,
            condition_flags.get(condition) if isinstance(condition_flags, dict) else None,
        ]
        if True in values:
            return "matched"
        if False in values:
            return "condition_not_met"
        if condition in {
            "self_switched_this_turn",
            "enemy_switched_this_turn",
            "target_switched_this_turn",
            "defender_switched_this_turn",
            "actor_switched_this_turn",
        }:
            return (
                "matched"
                if self._switch_condition_matches(battle_event, condition)
                else "condition_not_met"
            )
        if condition == "target_defeated":
            return "matched" if self._target_is_defeated(battle_event) else "condition_not_met"
        if condition == "any_response_success":
            for key in (
                "response_attack_success",
                "response_defense_success",
                "response_status_success",
            ):
                if self._condition_result(battle_event, key) == "matched":
                    return "matched"
            return "condition_not_met"
        if condition.endswith("_failed"):
            success_condition = f"{condition[:-7]}_success"
            success_values = [
                payload.get(success_condition),
                manual_flags.get(success_condition) if isinstance(manual_flags, dict) else None,
                (
                    condition_flags.get(success_condition)
                    if isinstance(condition_flags, dict)
                    else None
                ),
            ]
            if False in success_values:
                return "matched"
            if True in success_values:
                return "condition_not_met"
        return "unknown"

    def _resolve_resource_change_value(
        self,
        battle_event: BattleEvent,
        operation: dict,
    ) -> object:
        """解析资源变化数值，支持从被应对技能能耗读取。"""
        value_from = operation.get("value_from")
        if value_from not in {"responded_skill_energy_cost", "target_skill_energy_cost"}:
            return operation.get("value")
        skill_id = self._responded_skill_id(battle_event)
        if not skill_id:
            return None
        skill = self.db.get(SkillDefinition, skill_id)
        if skill is None or skill.deleted_at is not None:
            return None
        return max(int(skill.base_energy_cost or 0), 0)

    @staticmethod
    def _responded_skill_id(battle_event: BattleEvent) -> str | None:
        payload = loads_json(battle_event.payload_json, {})
        if not isinstance(payload, dict):
            return None
        for key in ("responded_skill_id", "target_skill_id", "interrupted_skill_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        responded_skill = payload.get("responded_skill")
        if isinstance(responded_skill, dict):
            value = responded_skill.get("skill_id")
            if isinstance(value, str) and value:
                return value
        return None

    def _target_is_defeated(self, battle_event: BattleEvent) -> bool:
        target_state = self._resolve_resource_target(
            battle_event,
            battle_event.target_side or "target_side",
        )
        if target_state is not None:
            return target_state.is_defeated is True
        payload = loads_json(battle_event.payload_json, {})
        if isinstance(payload, dict):
            if payload.get("target_defeated") is True:
                return True
            hp_after = payload.get("hp_percent_after")
            if isinstance(hp_after, int | float) and hp_after <= 0:
                return True
        return False

    def _switch_condition_matches(self, battle_event: BattleEvent, condition: str) -> bool:
        switched_sides = {
            side
            for side in self.db.scalars(
                select(BattleEvent.actor_side).where(
                    BattleEvent.battle_id == battle_event.battle_id,
                    BattleEvent.turn_number == battle_event.turn_number,
                    BattleEvent.event_type == "switch_elf",
                    BattleEvent.actor_side.is_not(None),
                    BattleEvent.is_voided.is_(False),
                )
            ).all()
            if side
        }
        if condition == "self_switched_this_turn":
            return Side.SELF.value in switched_sides
        if condition == "enemy_switched_this_turn":
            return Side.ENEMY.value in switched_sides
        if condition in {"target_switched_this_turn", "defender_switched_this_turn"}:
            return battle_event.target_side in switched_sides
        if condition == "actor_switched_this_turn":
            return battle_event.actor_side in switched_sides
        return False

    def _resolve_target(
        self,
        battle_event: BattleEvent,
        target: object,
        definition: EffectDefinition,
    ) -> dict:
        """把 operation.target 解析为状态挂载目标。"""
        battle = self.db.get(Battle, battle_event.battle_id)
        if battle is None or battle.deleted_at is not None:
            return {"status": "failed", "reason": "battle_missing"}

        target_side = self._resolve_target_side(battle_event, target)
        if definition.owner_scope == OwnerScope.SIDE.value:
            if target_side is None:
                return {"status": "failed", "reason": "target_side_missing"}
            return {
                "status": "resolved",
                "battle_id": battle_event.battle_id,
                "owner_side": target_side,
                "owner_elf_id": None,
                "owner_skill_slot_id": None,
                "field_id": None,
            }
        if definition.owner_scope == OwnerScope.FIELD.value:
            return {
                "status": "resolved",
                "battle_id": battle_event.battle_id,
                "owner_side": None,
                "owner_elf_id": None,
                "owner_skill_slot_id": None,
                "field_id": "main",
            }
        if definition.owner_scope == OwnerScope.ELF.value:
            if target_side is None:
                return {"status": "failed", "reason": "target_side_missing"}
            target_elf_id = self._resolve_target_elf_id(battle, battle_event, target_side)
            if target_elf_id is None:
                return {"status": "failed", "reason": "target_elf_id_missing"}
            return {
                "status": "resolved",
                "battle_id": battle_event.battle_id,
                "owner_side": target_side,
                "owner_elf_id": target_elf_id,
                "owner_skill_slot_id": None,
                "field_id": None,
            }
        if definition.owner_scope == OwnerScope.SKILL_SLOT.value:
            owner_skill_slot_id = None
            owner_side = target_side
            owner_elf_id = None
            if target in {"source_skill", "self_skill"} and battle_event.skill_id:
                owner_skill_slot_id = self._source_skill_slot_id(battle_event)
                owner_side = battle_event.actor_side
                owner_elf_id = battle_event.actor_elf_id
            elif target in {
                "enemy_current_turn_used_skill",
                "opponent_current_turn_used_skill",
                "target_current_turn_used_skill",
            }:
                target_side_for_slot = self._resolve_target_side(battle_event, "enemy_side")
                if target == "target_current_turn_used_skill":
                    target_side_for_slot = self._resolve_target_side(battle_event, "target_side")
                owner_skill_slot_id = self._current_turn_used_skill_slot_id(
                    battle_event,
                    target_side_for_slot,
                )
                owner_side = target_side_for_slot
            if owner_skill_slot_id is None:
                return {"status": "failed", "reason": "owner_skill_slot_id_missing"}
            return {
                "status": "resolved",
                "battle_id": battle_event.battle_id,
                "owner_side": owner_side,
                "owner_elf_id": owner_elf_id,
                "owner_skill_slot_id": owner_skill_slot_id,
                "field_id": None,
            }
        return {"status": "failed", "reason": f"unsupported_owner_scope:{definition.owner_scope}"}

    @staticmethod
    def _resolve_target_side(battle_event: BattleEvent, target: object) -> str | None:
        """解析目标阵营。"""
        if target in {"field", "battlefield", "all_field"}:
            return None
        if target in {"enemy_side", "opponent_side", "defender_side"}:
            return EffectOperationExecutor._opposite_side(battle_event.actor_side)
        if target in {"self_side", "actor_side", "source_side"}:
            return battle_event.actor_side
        if target in {"target_side", "defender", "target"}:
            return battle_event.target_side
        if target in {Side.SELF.value, Side.ENEMY.value}:
            return str(target)
        return battle_event.target_side or EffectOperationExecutor._opposite_side(
            battle_event.actor_side
        )

    @staticmethod
    def _resolve_target_elf_id(
        battle: Battle,
        battle_event: BattleEvent,
        target_side: str,
    ) -> str | None:
        """解析精灵目标。"""
        if battle_event.target_side == target_side and battle_event.target_elf_id:
            return battle_event.target_elf_id
        if battle_event.actor_side == target_side and battle_event.actor_elf_id:
            return battle_event.actor_elf_id
        if target_side == Side.SELF.value:
            return battle.self_active_elf_id
        if target_side == Side.ENEMY.value:
            return battle.enemy_active_elf_id
        return None

    def _source_skill_slot_id(self, battle_event: BattleEvent) -> str | None:
        """读取本次使用技能对应的运行时技能槽 ID。"""
        if (
            battle_event.actor_side is None
            or battle_event.actor_elf_id is None
            or battle_event.skill_id is None
        ):
            return None
        slot = self.db.scalars(
            select(BattleSkillSlot).where(
                BattleSkillSlot.battle_id == battle_event.battle_id,
                BattleSkillSlot.side == battle_event.actor_side,
                BattleSkillSlot.elf_id == battle_event.actor_elf_id,
                BattleSkillSlot.skill_id == battle_event.skill_id,
            )
        ).first()
        return slot.slot_id if slot is not None else None

    def _current_turn_used_skill_slot_id(
        self,
        battle_event: BattleEvent,
        target_side: str | None,
    ) -> str | None:
        """读取目标阵营本回合已经使用过的最后一个技能槽 ID。"""
        if target_side is None:
            return None
        used_event = self.db.scalars(
            select(BattleEvent)
            .where(
                BattleEvent.battle_id == battle_event.battle_id,
                BattleEvent.turn_number == battle_event.turn_number,
                BattleEvent.actor_side == target_side,
                BattleEvent.skill_id.is_not(None),
                BattleEvent.is_voided.is_(False),
            )
            .order_by(
                BattleEvent.action_order.desc().nullslast(),
                BattleEvent.created_at.desc(),
            )
        ).first()
        if used_event is None or used_event.skill_id is None or used_event.actor_elf_id is None:
            return None
        slot = self.db.scalars(
            select(BattleSkillSlot).where(
                BattleSkillSlot.battle_id == battle_event.battle_id,
                BattleSkillSlot.side == target_side,
                BattleSkillSlot.elf_id == used_event.actor_elf_id,
                BattleSkillSlot.skill_id == used_event.skill_id,
            )
        ).first()
        return slot.slot_id if slot is not None else None

    @staticmethod
    def _opposite_side(side: str | None) -> str | None:
        """返回对方阵营。"""
        if side == Side.SELF.value:
            return Side.ENEMY.value
        if side == Side.ENEMY.value:
            return Side.SELF.value
        return None

    def _resolve_layers(
        self,
        battle_event: BattleEvent,
        operation: dict,
        definition: EffectDefinition,
        target: dict,
    ) -> dict:
        """解析施加层数，并按状态定义 max_layers 截断。"""
        if operation.get("layers_from") in {
            "current_hit_count",
            "skill_hit_count",
            "effective_hit_count",
        }:
            return self._resolve_layers_from_current_hit_count(
                battle_event,
                operation,
                definition,
            )
        if operation.get("layers_from") in {"damage_hit_count", "current_damage_hit_count"}:
            return self._resolve_layers_from_damage_hit_count(
                battle_event,
                operation,
                definition,
            )
        if "layers_from" in operation:
            return self._resolve_dynamic_layers(operation, definition, target)
        operation_type = (
            operation.get("operation")
            or operation.get("op_type")
            or operation.get("type")
        )
        if operation_type == "dynamic_apply_effect" and "layers" not in operation:
            base_layers = operation.get("base_layers")
            use_count = operation.get("use_count")
            bonus_per_use = operation.get("layers_bonus_per_use", 0)
            if isinstance(base_layers, int) and isinstance(use_count, int):
                layers = base_layers + use_count * int(bonus_per_use or 0)
                if definition.max_layers is not None:
                    layers = min(layers, definition.max_layers)
                return {"status": "resolved", "layers": max(layers, 0)}
            return {"status": "unknown", "reason": "dynamic_layers_context_missing"}
        raw_layers = operation.get("layers", definition.default_layers)
        layers = (
            raw_layers
            if isinstance(raw_layers, int) and raw_layers > 0
            else definition.default_layers
        )
        if definition.max_layers is not None:
            layers = min(layers, definition.max_layers)
        return {"status": "resolved", "layers": layers}

    def _resolve_dynamic_layers(
        self,
        operation: dict,
        definition: EffectDefinition,
        target: dict,
    ) -> dict:
        """解析依赖当前状态的动态层数。"""
        layers_from = operation.get("layers_from")
        if layers_from not in {
            "existing_effect_layers",
            "target_existing_effect_layers",
            "enemy_existing_starfall_layers",
            "opponent_existing_effect_layers",
        }:
            return {"status": "unknown", "reason": "unsupported_layers_from"}
        source_effect_id = operation.get("source_effect_id") or operation.get("effect_id")
        if not isinstance(source_effect_id, str) or not source_effect_id:
            return {"status": "unknown", "reason": "source_effect_id_missing"}
        source_definition = self.db.get(EffectDefinition, source_effect_id)
        if source_definition is None or source_definition.deleted_at is not None:
            return {"status": "unknown", "reason": "source_effect_definition_missing"}
        source_target = self._resolve_dynamic_layers_source_target(
            layers_from,
            target,
            source_definition,
        )
        if source_target["status"] != "resolved":
            return {"status": "unknown", "reason": source_target["reason"]}
        existing = self._find_existing_instance(
            battle_id=str(source_target.get("battle_id")),
            definition=source_definition,
            owner_side=source_target.get("owner_side"),
            owner_elf_id=source_target.get("owner_elf_id"),
            owner_skill_slot_id=source_target.get("owner_skill_slot_id"),
            field_id=source_target.get("field_id"),
        )
        if existing is None or existing.layers <= 0:
            return {"status": "skipped", "reason": "dynamic_layers_zero"}
        layers = int(existing.layers * self._resolve_layers_multiplier(operation))
        if layers <= 0:
            return {"status": "skipped", "reason": "dynamic_layers_zero"}
        if definition.max_layers is not None:
            layers = min(layers, definition.max_layers)
        return {"status": "resolved", "layers": layers}

    def _resolve_layers_from_current_hit_count(
        self,
        battle_event: BattleEvent,
        operation: dict,
        definition: EffectDefinition,
    ) -> dict:
        """按当前连击数计算状态层数，例如每段获得 30%/60% 属性增益。"""
        hit_count_detail = self._resolve_current_hit_count(battle_event)
        if hit_count_detail["status"] != "resolved":
            return {
                "status": "unknown",
                "reason": hit_count_detail["reason"],
            }
        hit_count = int(hit_count_detail["hit_count"])
        layers_per_hit = self._positive_int(
            operation.get("layers_per_hit")
            or operation.get("layers_per_combo")
            or operation.get("layers_multiplier")
            or operation.get("layers_per_source_layer")
            or 1
        )
        base_layers = self._non_negative_int(operation.get("base_layers")) or 0
        layers = base_layers + hit_count * layers_per_hit
        if definition.max_layers is not None:
            layers = min(layers, definition.max_layers)
        return {
            "status": "resolved",
            "layers": max(layers, 0),
            "layers_from": operation.get("layers_from"),
            "hit_count": hit_count,
            "hit_count_source": hit_count_detail.get("source"),
            "layers_per_hit": layers_per_hit,
            "base_layers": base_layers,
        }

    def _resolve_layers_from_damage_hit_count(
        self,
        battle_event: BattleEvent,
        operation: dict,
        definition: EffectDefinition,
    ) -> dict:
        """按伤害事件的连击段数解析层数。"""
        payload = loads_json(battle_event.payload_json, {})
        if not isinstance(payload, dict):
            return {"status": "unknown", "reason": "payload_missing"}
        hit_count = self._positive_int(payload.get("hit_count"))
        if hit_count is None:
            damage_display_type = payload.get("damage_display_type")
            hit_count = 1 if damage_display_type in {None, "single_damage"} else None
        if hit_count is None:
            return {"status": "unknown", "reason": "damage_hit_count_missing"}
        layers_per_hit = self._positive_int(
            operation.get("layers_per_hit")
            or operation.get("layers_per_combo")
            or operation.get("layers_multiplier")
            or operation.get("layers_per_source_layer")
        ) or 1
        base_layers = self._non_negative_int(operation.get("base_layers")) or 0
        layers = base_layers + hit_count * layers_per_hit
        if definition.max_layers is not None:
            layers = min(layers, definition.max_layers)
        return {
            "status": "resolved",
            "layers": max(layers, 0),
            "layers_from": operation.get("layers_from"),
            "hit_count": hit_count,
            "layers_per_hit": layers_per_hit,
            "base_layers": base_layers,
        }

    def _resolve_current_hit_count(self, battle_event: BattleEvent) -> dict:
        """读取技能事件 payload 中的最终连击数，缺失时回退到技能 hit_rule_json。"""
        payload = loads_json(battle_event.payload_json, {})
        if not isinstance(payload, dict):
            payload = {}
        skill_runtime = payload.get("skill_runtime")
        if isinstance(skill_runtime, dict):
            runtime_hit_count = self._positive_int(skill_runtime.get("effective_hit_count"))
            if runtime_hit_count is not None:
                return {
                    "status": "resolved",
                    "hit_count": runtime_hit_count,
                    "source": "skill_runtime",
                }
        manual_hit_count = self._positive_int(payload.get("hit_count"))
        if manual_hit_count is not None:
            return {
                "status": "resolved",
                "hit_count": manual_hit_count,
                "source": "manual_payload",
            }
        context = DamageFormulaContext(
            battle_id=battle_event.battle_id,
            attacker_side=str(battle_event.actor_side or ""),
            attacker_elf_id=str(battle_event.actor_elf_id or ""),
            defender_side=str(
                battle_event.target_side
                or self._opposite_side(battle_event.actor_side)
                or ""
            ),
            defender_elf_id=str(battle_event.target_elf_id or ""),
            skill_id=battle_event.skill_id,
            formula_type="attack",
            snapshot_payload=self._active_effect_snapshot_payload(battle_event.battle_id),
        )
        details = HitRuleResolver(self.db).resolve_hit_rule(context, payload)
        hit_rule = details.get("hit_rule") if isinstance(details, dict) else None
        source = (
            hit_rule.get("source")
            if isinstance(hit_rule, dict) and isinstance(hit_rule.get("source"), str)
            else "context_default"
        )
        return {
            "status": "resolved",
            "hit_count": max(int(context.hit_count or 1), 1),
            "source": source,
        }

    def _active_effect_snapshot_payload(self, battle_id: str) -> list[dict]:
        """把当前 active 状态转成 HitRuleResolver 可读取的轻量快照。"""
        return [
            {
                "instance_id": item.instance_id,
                "effect_id": item.effect_id,
                "category": item.category,
                "owner_scope": item.owner_scope,
                "owner_side": item.owner_side,
                "owner_elf_id": item.owner_elf_id,
                "owner_skill_slot_id": item.owner_skill_slot_id,
                "field_id": item.field_id,
                "layers": item.layers,
            }
            for item in self.db.scalars(
                select(BattleEffectInstance).where(
                    BattleEffectInstance.battle_id == battle_id,
                    BattleEffectInstance.is_active.is_(True),
                )
            ).all()
        ]

    @staticmethod
    def _layers_resolution_detail(layers_result: dict) -> dict | None:
        detail = {
            key: value
            for key, value in layers_result.items()
            if key not in {"status", "layers"}
        }
        return detail or None

    @staticmethod
    def _positive_int(value: object) -> int | None:
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _non_negative_int(value: object) -> int | None:
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    def _resolve_dynamic_layers_source_target(
        self,
        layers_from: object,
        target: dict,
        source_definition: EffectDefinition,
    ) -> dict:
        """解析动态层数读取源，默认读取本次操作目标，必要时读取对方当前精灵。"""
        if layers_from == "opponent_existing_effect_layers":
            battle_id = str(target.get("battle_id") or "")
            battle = self.db.get(Battle, battle_id)
            if battle is None or battle.deleted_at is not None:
                return {"status": "unknown", "reason": "battle_missing"}
            owner_side = self._opposite_side(target.get("owner_side"))
            if owner_side is None:
                return {"status": "unknown", "reason": "opponent_side_missing"}
            owner_elf_id = None
            if source_definition.owner_scope == OwnerScope.ELF.value:
                owner_elf_id = (
                    battle.self_active_elf_id
                    if owner_side == Side.SELF.value
                    else battle.enemy_active_elf_id
                )
                if owner_elf_id is None:
                    return {"status": "unknown", "reason": "opponent_active_elf_missing"}
            return {
                "status": "resolved",
                "battle_id": battle_id,
                "owner_side": owner_side,
                "owner_elf_id": owner_elf_id,
                "owner_skill_slot_id": None,
                "field_id": None,
            }
        return {
            "status": "resolved",
            "battle_id": target.get("battle_id"),
            "owner_side": target.get("owner_side"),
            "owner_elf_id": target.get("owner_elf_id"),
            "owner_skill_slot_id": target.get("owner_skill_slot_id"),
            "field_id": target.get("field_id"),
        }

    @staticmethod
    def _resolve_layers_multiplier(operation: dict) -> int:
        """解析动态层数倍率；用于“每层异常转为多层属性修正”。"""
        raw_multiplier = (
            operation.get("layers_multiplier")
            or operation.get("layers_per_source_layer")
            or 1
        )
        try:
            multiplier = int(raw_multiplier)
        except (TypeError, ValueError):
            return 1
        return max(multiplier, 0)

    def _clear_matching_effects(
        self,
        *,
        battle_event: BattleEvent,
        operation: dict,
        effect_ids: set[str] | None,
        categories: set[str] | None,
        polarity: str | None,
        conflict_group: str | None,
        exclude_effect_id: str | None,
        reason: str,
    ) -> list[dict]:
        """按选择器清除当前 active 状态。"""
        target_side = self._resolve_target_side(battle_event, operation.get("target"))
        definitions_by_id = self._load_effect_definitions()
        removed: list[dict] = []
        instances = self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle_event.battle_id,
                BattleEffectInstance.is_active.is_(True),
            )
        ).all()
        for instance in instances:
            definition = definitions_by_id.get(instance.effect_id)
            if definition is None:
                continue
            if exclude_effect_id is not None and instance.effect_id == exclude_effect_id:
                continue
            if effect_ids and instance.effect_id not in effect_ids:
                continue
            if categories and instance.category not in categories:
                continue
            if polarity is not None and definition.polarity != polarity:
                continue
            if conflict_group and definition.conflict_group != conflict_group:
                continue
            if target_side is not None and instance.owner_scope != OwnerScope.FIELD.value:
                if instance.owner_side != target_side:
                    continue

            layers_before = instance.layers
            instance.is_active = False
            instance.layers = 0
            instance.last_updated_turn = battle_event.turn_number
            self._create_effect_change_event(
                battle_event=battle_event,
                definition=definition,
                instance=instance,
                change_type="clear",
                layers_before=layers_before,
                condition_branch=None,
                reason=reason,
            )
            removed.append(
                {
                    "effect_id": instance.effect_id,
                    "effect_instance_id": instance.instance_id,
                    "layers_before": layers_before,
                    "layers_after": 0,
                }
            )
        return removed

    def _load_effect_definitions(self) -> dict[str, EffectDefinition]:
        """读取当前全部 active 状态定义。"""
        return {
            item.effect_id: item
            for item in self.db.scalars(
                select(EffectDefinition).where(EffectDefinition.deleted_at.is_(None))
            ).all()
        }

    def _resolve_resource_target(
        self,
        battle_event: BattleEvent,
        target: object,
    ) -> BattleElfState | None:
        """解析资源变化目标精灵。"""
        battle = self.db.get(Battle, battle_event.battle_id)
        if battle is None or battle.deleted_at is not None:
            return None
        target_side = self._resolve_target_side(battle_event, target)
        if target_side is None:
            return None
        target_elf_id = self._resolve_target_elf_id(battle, battle_event, target_side)
        if target_elf_id is None:
            return None
        return self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == battle_event.battle_id,
                BattleElfState.side == target_side,
                BattleElfState.elf_id == target_elf_id,
            )
        ).first()

    @staticmethod
    def _apply_hp_resource_change(
        target_state: BattleElfState,
        change_type: str,
        raw_value: float,
        value_type: str,
    ) -> float | int | None:
        """更新目标生命值。"""
        before_value = target_state.current_hp_value
        if before_value is None:
            return None
        value = raw_value
        if value_type == "percent":
            max_hp = EffectOperationExecutor._max_hp(target_state)
            if max_hp is None:
                return before_value
            value = max_hp * raw_value
        if change_type in {"damage", "consume", "lose"}:
            target_state.current_hp_value = max(int(before_value - value), 0)
        elif change_type in {"heal", "gain", "recover"}:
            max_hp = EffectOperationExecutor._max_hp(target_state)
            next_value = int(before_value + value)
            target_state.current_hp_value = min(next_value, max_hp) if max_hp else next_value
        elif change_type == "manual_set":
            target_state.current_hp_value = max(int(value), 0)
        max_hp = EffectOperationExecutor._max_hp(target_state)
        if max_hp:
            target_state.current_hp_percent = round(
                (target_state.current_hp_value / max_hp) * 100,
                4,
            )
        target_state.is_defeated = (
            target_state.current_hp_value == 0 or target_state.current_hp_percent == 0
        )
        return target_state.current_hp_value

    @staticmethod
    def _apply_energy_resource_change(
        target_state: BattleElfState,
        change_type: str,
        raw_value: float,
        max_value: int | None = None,
    ) -> float | int | None:
        """更新目标能量值。"""
        before_value = target_state.energy
        if before_value is None:
            return None
        if change_type in {"consume", "damage", "lose"}:
            target_state.energy = max(int(before_value - raw_value), 0)
        elif change_type in {"gain", "heal", "recover"}:
            target_state.energy = int(before_value + raw_value)
        elif change_type == "manual_set":
            target_state.energy = max(int(raw_value), 0)
        if max_value is not None:
            target_state.energy = min(target_state.energy, max_value)
        return target_state.energy

    def _resolve_resource_targets(
        self,
        battle_event: BattleEvent,
        target: object,
    ) -> list[BattleElfState]:
        """解析资源变化的多目标列表。"""
        if target in {"bench_allies", "ally_bench", "self_bench"}:
            battle = self.db.get(Battle, battle_event.battle_id)
            if battle is None or battle.deleted_at is not None or battle_event.actor_side is None:
                return []
            active_elf_id = (
                battle.self_active_elf_id
                if battle_event.actor_side == Side.SELF.value
                else battle.enemy_active_elf_id
            )
            return list(
                self.db.scalars(
                    select(BattleElfState).where(
                        BattleElfState.battle_id == battle_event.battle_id,
                        BattleElfState.side == battle_event.actor_side,
                        BattleElfState.elf_id != active_elf_id,
                        BattleElfState.is_defeated.is_(False),
                    )
                ).all()
            )
        resolved = self._resolve_resource_target(battle_event, target)
        return [resolved] if resolved is not None else []

    @staticmethod
    def _optional_int(value: object) -> int | None:
        """把可选数值解析为整数。"""
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    def _add_resource_event_for_state(
        self,
        *,
        battle_event: BattleEvent,
        state: BattleElfState,
        resource_type: str,
        change_type: str,
        value: float,
        value_type: str,
        before_value: float | int | None,
        after_value: float | int | None,
    ) -> ResourceChangeEvent:
        """为资源变化写入统一的 ResourceChangeEvent。"""
        event = ResourceChangeEvent(
            event_id=f"resource_event_{uuid4().hex}",
            battle_id=battle_event.battle_id,
            battle_event_id=battle_event.event_id,
            resource_type=resource_type,
            change_type=change_type,
            source_side=battle_event.actor_side,
            source_elf_id=battle_event.actor_elf_id,
            target_side=state.side,
            target_elf_id=state.elf_id,
            value_type=value_type,
            value=value,
            before_value=float(before_value) if before_value is not None else None,
            after_value=float(after_value) if after_value is not None else None,
            confidence=1.0,
            manual_override=False,
        )
        self.db.add(event)
        self.db.flush()
        return event

    @staticmethod
    def _current_hp_percent(target_state: BattleElfState, max_hp: int) -> float:
        """读取当前生命百分比；字段缺失时从当前 HP 反推。"""
        if target_state.current_hp_percent is not None:
            return max(0.0, min(float(target_state.current_hp_percent), 100.0))
        if target_state.current_hp_value is None or max_hp <= 0:
            return 100.0
        return max(0.0, min(float(target_state.current_hp_value) / max_hp * 100, 100.0))

    @staticmethod
    def _hp_from_percent(max_hp: int, percent: float) -> int:
        """按百分比换算 HP，生命比例交换不会直接把任一方置为 0。"""
        safe_percent = max(0.0, min(float(percent), 100.0))
        return max(int(floor(max_hp * safe_percent / 100)), 1)

    @staticmethod
    def _max_hp(target_state: BattleElfState) -> int | None:
        """从运行时面板读取最大生命。"""
        panel_stats = loads_json(target_state.panel_stats_json, {})
        if not isinstance(panel_stats, dict):
            return None
        try:
            hp = int(panel_stats["hp"])
        except (KeyError, TypeError, ValueError):
            return None
        return hp if hp > 0 else None

    @staticmethod
    def _normalize_str_set(value: object) -> set[str]:
        """把单值或列表归一化为字符串集合。"""
        if isinstance(value, str) and value:
            return {value}
        if isinstance(value, list):
            return {str(item) for item in value if isinstance(item, str) and item}
        return set()

    def _find_existing_instance(
        self,
        *,
        battle_id: str,
        definition: EffectDefinition,
        owner_side: str | None,
        owner_elf_id: str | None,
        owner_skill_slot_id: str | None,
        field_id: str | None,
    ) -> BattleEffectInstance | None:
        """查找同一挂载目标上的现有生效实例。"""
        stmt = select(BattleEffectInstance).where(
            BattleEffectInstance.battle_id == battle_id,
            BattleEffectInstance.effect_id == definition.effect_id,
            BattleEffectInstance.owner_scope == definition.owner_scope,
            BattleEffectInstance.owner_side == owner_side,
            BattleEffectInstance.owner_elf_id == owner_elf_id,
            BattleEffectInstance.owner_skill_slot_id == owner_skill_slot_id,
            BattleEffectInstance.field_id == field_id,
            BattleEffectInstance.is_active.is_(True),
        )
        return self.db.scalars(stmt).first()

    def _create_instance(
        self,
        *,
        battle_event: BattleEvent,
        definition: EffectDefinition,
        target: dict,
        layers: int,
        operation: dict,
    ) -> BattleEffectInstance:
        """创建新的状态实例。"""
        instance = BattleEffectInstance(
            instance_id=f"effect_instance_{uuid4().hex}",
            battle_id=battle_event.battle_id,
            effect_id=definition.effect_id,
            category=definition.category,
            owner_scope=definition.owner_scope,
            owner_side=target.get("owner_side"),
            owner_elf_id=target.get("owner_elf_id"),
            owner_skill_slot_id=target.get("owner_skill_slot_id"),
            field_id=target.get("field_id"),
            source_side=battle_event.actor_side,
            source_elf_id=battle_event.actor_elf_id,
            source_skill_id=battle_event.skill_id,
            source_event_id=battle_event.event_id,
            layers=layers,
            remaining_turns=self._resolve_remaining_turns(operation, definition),
            remaining_uses=self._resolve_remaining_uses(operation, definition),
            is_active=True,
            applied_turn=battle_event.turn_number,
            expire_turn=self._calculate_expire_turn(
                battle_event.turn_number,
                operation,
                definition,
            ),
            last_updated_turn=battle_event.turn_number,
            recognition_source=EventSource.SYSTEM_CALCULATED.value,
            recognition_confidence=1.0,
            manual_override=False,
            notes="skill_effect_operation",
        )
        self.db.add(instance)
        return instance

    @staticmethod
    def _update_existing_instance(
        *,
        instance: BattleEffectInstance,
        definition: EffectDefinition,
        layers: int,
        turn_number: int,
        operation: dict,
    ) -> None:
        """按 stack_rule 更新现有状态实例。"""
        if definition.stack_rule in {"add", "add_layers"}:
            next_layers = instance.layers + layers
            if definition.max_layers is not None:
                next_layers = min(next_layers, definition.max_layers)
            instance.layers = next_layers
        elif definition.stack_rule == "refresh":
            pass
        else:
            instance.layers = layers
        instance.remaining_turns = EffectOperationExecutor._resolve_remaining_turns(
            operation,
            definition,
        )
        instance.remaining_uses = EffectOperationExecutor._resolve_remaining_uses(
            operation,
            definition,
        )
        instance.expire_turn = EffectOperationExecutor._calculate_expire_turn(
            turn_number,
            operation,
            definition,
        )
        instance.last_updated_turn = turn_number
        instance.recognition_source = EventSource.SYSTEM_CALCULATED.value
        instance.manual_override = False

    def _create_effect_change_event(
        self,
        *,
        battle_event: BattleEvent,
        definition: EffectDefinition,
        instance: BattleEffectInstance,
        change_type: str,
        layers_before: int | None,
        condition_branch: str | None,
        reason: str,
    ) -> EffectChangeEvent:
        """创建与技能事件绑定的状态变化详情。"""
        event = EffectChangeEvent(
            event_id=f"effect_change_{uuid4().hex}",
            battle_id=battle_event.battle_id,
            battle_event_id=battle_event.event_id,
            turn_number=battle_event.turn_number,
            change_type=change_type,
            effect_instance_id=instance.instance_id,
            effect_id=definition.effect_id,
            effect_name=definition.effect_name,
            category=definition.category,
            target_side=instance.owner_side,
            target_elf_id=instance.owner_elf_id,
            target_skill_slot_id=instance.owner_skill_slot_id,
            owner_scope=instance.owner_scope,
            layers_before=layers_before,
            layers_after=instance.layers,
            duration_before=None,
            duration_after=instance.remaining_turns,
            source_skill_id=battle_event.skill_id,
            source_elf_id=battle_event.actor_elf_id,
            condition_branch=condition_branch,
            reason=reason,
            source=EventSource.SYSTEM_CALCULATED.value,
            recognition_confidence=1.0,
            manual_override=False,
        )
        self.db.add(event)
        self.db.flush()
        return event

    @staticmethod
    def _resolve_remaining_turns(operation: dict, definition: EffectDefinition) -> int | None:
        """解析剩余回合，保留显式 0。"""
        value = operation.get("remaining_turns")
        return value if isinstance(value, int) else definition.default_duration_turns

    @staticmethod
    def _resolve_remaining_uses(operation: dict, definition: EffectDefinition) -> int | None:
        """解析剩余次数，保留显式 0。"""
        value = operation.get("remaining_uses")
        return value if isinstance(value, int) else definition.default_duration_uses

    @staticmethod
    def _calculate_expire_turn(
        turn_number: int,
        operation: dict,
        definition: EffectDefinition,
    ) -> int | None:
        """根据剩余回合计算过期回合。"""
        remaining_turns = EffectOperationExecutor._resolve_remaining_turns(operation, definition)
        if remaining_turns is None:
            return None
        return turn_number + remaining_turns

    @staticmethod
    def _skipped(operation: dict, operation_index: int, reason: str) -> dict:
        """生成跳过摘要。"""
        return {
            "status": "skipped",
            "reason": reason,
            "operation_index": operation_index,
            "operation": (
                operation.get("operation")
                or operation.get("op_type")
                or operation.get("type")
            ),
            "effect_id": operation.get("effect_id"),
        }
