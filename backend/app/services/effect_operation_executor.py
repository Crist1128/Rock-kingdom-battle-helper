"""技能效果操作执行器。

本模块负责把 SkillDefinition.effect_operations_json 中的结构化操作落到战斗运行时。
阶段 D 支持常见状态、天气和资源操作；对条件不明确或上下文不足的分支只记录
skipped/unknown，不强行改写状态。
"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import EventSource, OwnerScope, Side
from app.models.battle import Battle, BattleElfState
from app.models.effect import BattleEffectInstance
from app.models.event import BattleEvent, EffectChangeEvent, ResourceChangeEvent
from app.models.static import EffectDefinition, SkillDefinition
from app.utils.json import loads_json


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
        "multiply_layers",
        "conditional_branch",
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
        if timing not in (None, "", "on_skill_use", "after_damage_or_skill_use"):
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
        if operation_type == "resource_change":
            return self._execute_resource_change(battle_event, operation, operation_index)
        if operation_type == "clear_effects":
            return self._execute_clear_effects(battle_event, operation, operation_index)

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

        layers_result = self._resolve_layers(operation, definition, target)
        if layers_result["status"] != "resolved":
            return {
                "status": "unknown" if layers_result["status"] == "unknown" else "skipped",
                "reason": layers_result["reason"],
                "operation_index": operation_index,
                "operation": operation_type,
                "effect_id": effect_id,
            }
        layers = int(layers_result["layers"])
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
        }

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
            conflict_group=definition.conflict_group or "weather",
            exclude_effect_id=definition.effect_id,
            reason="change_weather_replace",
        )
        target = self._resolve_target(battle_event, "field", definition)
        if target["status"] != "resolved":
            return self._skipped(operation, operation_index, target["reason"])
        layers_result = self._resolve_layers(operation, definition, target)
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
        if not effect_ids and isinstance(operation.get("effect_id"), str):
            effect_ids = {str(operation["effect_id"])}
        if not effect_ids and not categories:
            return self._skipped(operation, operation_index, "clear_selector_missing")
        removed = self._clear_matching_effects(
            battle_event=battle_event,
            operation=operation,
            effect_ids=effect_ids,
            categories=categories,
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
        raw_value = operation.get("value")
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
            )
        else:
            return self._skipped(operation, operation_index, "unsupported_resource_type")

        self.db.add(
            ResourceChangeEvent(
                event_id=f"resource_event_{uuid4().hex}",
                battle_id=battle_event.battle_id,
                battle_event_id=battle_event.event_id,
                resource_type=resource_type,
                change_type=change_type,
                source_side=battle_event.actor_side,
                source_elf_id=battle_event.actor_elf_id,
                target_side=target_state.side,
                target_elf_id=target_state.elf_id,
                value_type=value_type,
                value=float(raw_value),
                before_value=float(before_value) if before_value is not None else None,
                after_value=float(after_value) if after_value is not None else None,
                confidence=1.0,
                manual_override=False,
            )
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

    def _condition_result(self, battle_event: BattleEvent, condition: object) -> str:
        """判断条件分支是否满足；未知条件只返回 unknown。"""
        if condition in self.ALWAYS_CONDITIONS:
            return "matched"
        payload = loads_json(battle_event.payload_json, {})
        if not isinstance(payload, dict) or not isinstance(condition, str):
            return "unknown"
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
        return "unknown"

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
            owner_skill_slot_id = (
                battle_event.skill_id if target in {"source_skill", "self_skill"} else None
            )
            if owner_skill_slot_id is None:
                return {"status": "failed", "reason": "owner_skill_slot_id_missing"}
            return {
                "status": "resolved",
                "battle_id": battle_event.battle_id,
                "owner_side": target_side,
                "owner_elf_id": None,
                "owner_skill_slot_id": owner_skill_slot_id,
                "field_id": None,
            }
        return {"status": "failed", "reason": f"unsupported_owner_scope:{definition.owner_scope}"}

    @staticmethod
    def _resolve_target_side(battle_event: BattleEvent, target: object) -> str | None:
        """解析目标阵营。"""
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
        operation: dict,
        definition: EffectDefinition,
        target: dict,
    ) -> dict:
        """解析施加层数，并按状态定义 max_layers 截断。"""
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
        }:
            return {"status": "unknown", "reason": "unsupported_layers_from"}
        source_effect_id = operation.get("source_effect_id") or operation.get("effect_id")
        if not isinstance(source_effect_id, str) or not source_effect_id:
            return {"status": "unknown", "reason": "source_effect_id_missing"}
        source_definition = self.db.get(EffectDefinition, source_effect_id)
        if source_definition is None or source_definition.deleted_at is not None:
            return {"status": "unknown", "reason": "source_effect_definition_missing"}
        existing = self._find_existing_instance(
            battle_id=str(target.get("battle_id")),
            definition=source_definition,
            owner_side=target.get("owner_side"),
            owner_elf_id=target.get("owner_elf_id"),
            owner_skill_slot_id=target.get("owner_skill_slot_id"),
            field_id=target.get("field_id"),
        )
        if existing is None or existing.layers <= 0:
            return {"status": "skipped", "reason": "dynamic_layers_zero"}
        layers = existing.layers
        if definition.max_layers is not None:
            layers = min(layers, definition.max_layers)
        return {"status": "resolved", "layers": layers}

    def _clear_matching_effects(
        self,
        *,
        battle_event: BattleEvent,
        operation: dict,
        effect_ids: set[str] | None,
        categories: set[str] | None,
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
        return target_state.energy

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
