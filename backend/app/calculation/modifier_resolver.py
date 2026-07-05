"""公式修正项解析器。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculation.formula_context import DamageFormulaContext
from app.core.element_aliases import element_type_matches
from app.models.battle import BattleElfState, BattleSkillSlot
from app.models.event import BattleEvent
from app.models.static import EffectDefinition, SkillDefinition
from app.utils.json import loads_json


class ModifierResolver:
    """把减伤、天气等结构化修正项解析为公式上下文。"""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def resolve_formula_modifiers(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """解析当前 E 阶段已确认可消费的公式修正项。"""
        details: dict[str, Any] = {}
        self._resolve_weather_multiplier(context, payload, details)
        self._resolve_stat_stage_multiplier(context, payload, details)
        self._resolve_damage_reductions(context, payload, details)
        self._resolve_dynamic_power_rules(context, payload, details)
        return details

    def _resolve_dynamic_power_rules(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        """解析已确认的技能动态威力分支。"""
        rules = self._dynamic_power_rules(context, payload)
        if not rules:
            return

        applied: list[dict[str, Any]] = []
        for index, rule in enumerate(rules):
            condition = rule.get("condition")
            if isinstance(condition, str) and condition:
                condition_result = self._condition_matches(context, payload, condition)
                if condition_result != "matched":
                    if condition_result == "unknown":
                        context.unknown_factors.append(f"dynamic_power_condition_unknown:{condition}")
                    applied.append(
                        {
                            "status": condition_result,
                            "index": index,
                            "condition": condition,
                        }
                    )
                    continue

            resolved = self._resolve_single_dynamic_power_rule(context, rule)
            if resolved["status"] == "unknown":
                context.unknown_factors.append(
                    f"dynamic_power_rule_unknown:{index}:{resolved.get('reason')}"
                )
            elif resolved["status"] == "resolved":
                power_add = resolved.get("power_add")
                if isinstance(power_add, Decimal):
                    context.flat_power_bonus = (
                        Decimal(str(context.flat_power_bonus)) + power_add
                    )
                multiplier = resolved.get("power_multiplier")
                if isinstance(multiplier, Decimal):
                    context.power_multiplier = (
                        Decimal(str(context.power_multiplier)) * multiplier
                    )
            applied.append(self._stringify_detail({"index": index, **resolved}))

        if applied:
            details["dynamic_power_rules"] = applied

    def _dynamic_power_rules(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        payload_rules = payload.get("dynamic_power_rules")
        if isinstance(payload_rules, list):
            rules.extend(item for item in payload_rules if isinstance(item, dict))
        elif isinstance(payload.get("dynamic_power_rule"), dict):
            rules.append(payload["dynamic_power_rule"])

        if self.db is not None and context.skill_id:
            skill = self.db.get(SkillDefinition, context.skill_id)
            if skill is not None and skill.deleted_at is None:
                damage_rule = loads_json(skill.damage_rule_json, {})
                if isinstance(damage_rule, dict):
                    skill_rules = damage_rule.get("dynamic_power_rules")
                    if isinstance(skill_rules, list):
                        rules.extend(item for item in skill_rules if isinstance(item, dict))
                    elif isinstance(damage_rule.get("dynamic_power_rule"), dict):
                        rules.append(damage_rule["dynamic_power_rule"])
        return rules

    def _resolve_single_dynamic_power_rule(
        self,
        context: DamageFormulaContext,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        if rule.get("power_multiplier") is not None:
            multiplier = self._to_decimal(rule["power_multiplier"])
            return {
                "status": "resolved",
                "rule_type": "fixed_power_multiplier",
                "power_multiplier": multiplier,
            }
        if rule.get("power_add") is not None and not self._has_dynamic_source(rule):
            return {
                "status": "resolved",
                "rule_type": "fixed_power_add",
                "power_add": self._to_decimal(rule["power_add"]),
            }
        if rule.get("missing_hp_percent_step") is not None:
            return self._resolve_missing_hp_power_rule(context, rule)
        if rule.get("hp_percent_threshold") is not None:
            return self._resolve_hp_threshold_power_rule(context, rule)
        if rule.get("source_resource") == "energy":
            return self._resolve_resource_power_rule(context, rule)
        if rule.get("source_skill_slot") == "current_skill_cost_delta":
            return self._resolve_skill_slot_cost_delta_power_rule(context, rule)
        if self._has_dynamic_source(rule):
            return self._resolve_effect_layer_power_rule(context, rule)
        return {"status": "unknown", "reason": "unsupported_dynamic_power_rule"}

    @staticmethod
    def _has_dynamic_source(rule: dict[str, Any]) -> bool:
        return any(
            key in rule
            for key in (
                "source_effect_id",
                "source_effect_ids",
                "source_category",
                "source_categories",
            )
        )

    def _resolve_effect_layer_power_rule(
        self,
        context: DamageFormulaContext,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        layer_result = self._snapshot_layers_for_power_rule(context, rule)
        if layer_result["status"] != "resolved":
            return layer_result
        layers = layer_result["layers"]
        if layers <= 0:
            return {
                "status": "skipped",
                "rule_type": "effect_layer_power",
                "reason": "source_layers_zero",
                **layer_result,
            }
        power_add = Decimal("0")
        multiplier: Decimal | None = None
        if rule.get("power_add_per_layer") is not None:
            power_add += self._to_decimal(rule["power_add_per_layer"]) * layers
        if rule.get("power_add_if_present") is not None:
            power_add += self._to_decimal(rule["power_add_if_present"])
        if rule.get("power_add") is not None:
            power_add += self._to_decimal(rule["power_add"])
        if rule.get("power_multiplier_if_present") is not None:
            multiplier = self._to_decimal(rule["power_multiplier_if_present"])
        return {
            "status": "resolved",
            "rule_type": "effect_layer_power",
            "source_target": rule.get("source_target"),
            "layers": layers,
            "power_add": power_add,
            "power_multiplier": multiplier,
            "matched_instances": layer_result["matched_instances"],
        }

    def _resolve_missing_hp_power_rule(
        self,
        context: DamageFormulaContext,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        hp_percent = self._state_hp_percent(context, target="actor")
        if hp_percent is None:
            return {"status": "unknown", "reason": "actor_hp_percent_missing"}
        missing = max(Decimal("100") - hp_percent, Decimal("0"))
        step = self._to_decimal(rule["missing_hp_percent_step"])
        if step <= 0:
            return {"status": "unknown", "reason": "missing_hp_percent_step_invalid"}
        steps = int(missing // step)
        power_add = self._to_decimal(rule.get("power_add_per_step", 0)) * steps
        capped = False
        if rule.get("min_power_after_add") is not None:
            min_power = self._to_decimal(rule["min_power_after_add"])
            base_power = self._to_decimal(context.base_power)
            existing_flat_bonus = self._to_decimal(context.flat_power_bonus)
            if base_power + existing_flat_bonus + power_add < min_power:
                power_add = min_power - base_power - existing_flat_bonus
                capped = True
        return {
            "status": "resolved",
            "rule_type": "missing_hp_power_add",
            "hp_percent": hp_percent,
            "missing_hp_percent": missing,
            "step": step,
            "steps": steps,
            "power_add": power_add,
            "capped": capped,
        }

    def _resolve_resource_power_rule(
        self,
        context: DamageFormulaContext,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._state_for_target(context, str(rule.get("source_target") or "defender_side"))
        if state is None or state.energy is None:
            return {"status": "unknown", "reason": "source_resource_missing"}
        energy = Decimal(str(state.energy))
        threshold = rule.get("threshold")
        operator = str(rule.get("operator") or "")
        if threshold is not None and operator:
            threshold_decimal = self._to_decimal(threshold)
            matched = self._compare_decimal(energy, operator, threshold_decimal)
            if matched is None:
                return {"status": "unknown", "reason": "resource_condition_operator_invalid"}
            if not matched:
                return {
                    "status": "skipped",
                    "rule_type": "resource_power_condition",
                    "source_resource": "energy",
                    "source_target": rule.get("source_target"),
                    "resource_value": energy,
                    "operator": operator,
                    "threshold": threshold_decimal,
                }
            result: dict[str, Any] = {
                "status": "resolved",
                "rule_type": "resource_power_condition",
                "source_resource": "energy",
                "source_target": rule.get("source_target"),
                "resource_value": energy,
                "operator": operator,
                "threshold": threshold_decimal,
            }
            if rule.get("power_multiplier") is not None:
                result["power_multiplier"] = self._to_decimal(rule["power_multiplier"])
            if rule.get("power_add") is not None:
                result["power_add"] = self._to_decimal(rule["power_add"])
            return result
        multiplier_delta = self._to_decimal(rule.get("power_multiplier_delta_per_point", 0))
        multiplier = Decimal("1") + energy * multiplier_delta
        capped = False
        if multiplier < 0:
            multiplier = Decimal("0")
            capped = True
        return {
            "status": "resolved",
            "rule_type": "resource_power_multiplier",
            "source_resource": "energy",
            "source_target": rule.get("source_target"),
            "resource_value": energy,
            "power_multiplier_delta_per_point": multiplier_delta,
            "power_multiplier": multiplier,
            "capped_at_zero": capped,
        }

    def _resolve_hp_threshold_power_rule(
        self,
        context: DamageFormulaContext,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        source_target = str(rule.get("source_target") or "actor")
        hp_percent = self._state_hp_percent(context, target=source_target)
        if hp_percent is None:
            return {"status": "unknown", "reason": "hp_percent_missing"}
        operator = str(rule.get("operator") or "gt")
        threshold = self._to_decimal(rule["hp_percent_threshold"])
        matched = self._compare_decimal(hp_percent, operator, threshold)
        if matched is None:
            return {"status": "unknown", "reason": "hp_percent_operator_invalid"}
        if not matched:
            return {
                "status": "skipped",
                "rule_type": "hp_threshold_power",
                "source_target": source_target,
                "hp_percent": hp_percent,
                "operator": operator,
                "threshold": threshold,
            }
        result: dict[str, Any] = {
            "status": "resolved",
            "rule_type": "hp_threshold_power",
            "source_target": source_target,
            "hp_percent": hp_percent,
            "operator": operator,
            "threshold": threshold,
        }
        if rule.get("power_add") is not None:
            result["power_add"] = self._to_decimal(rule["power_add"])
        if rule.get("power_multiplier") is not None:
            result["power_multiplier"] = self._to_decimal(rule["power_multiplier"])
        return result

    def _resolve_skill_slot_cost_delta_power_rule(
        self,
        context: DamageFormulaContext,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        if self.db is None or not context.battle_id or not context.skill_id:
            return {"status": "unknown", "reason": "skill_slot_context_missing"}
        slot = self.db.scalars(
            select(BattleSkillSlot).where(
                BattleSkillSlot.battle_id == context.battle_id,
                BattleSkillSlot.side == context.attacker_side,
                BattleSkillSlot.elf_id == context.attacker_elf_id,
                BattleSkillSlot.skill_id == context.skill_id,
            )
        ).first()
        skill = self.db.get(SkillDefinition, context.skill_id)
        if slot is None or skill is None or skill.deleted_at is not None:
            return {"status": "unknown", "reason": "skill_slot_or_definition_missing"}
        current_cost = (
            slot.current_energy_cost
            if slot.current_energy_cost is not None
            else skill.base_energy_cost
        )
        delta = Decimal(str(current_cost - skill.base_energy_cost))
        positive_delta = max(delta, Decimal("0"))
        power_add = positive_delta * self._to_decimal(rule.get("power_add_per_cost_delta", 0))
        return {
            "status": "resolved",
            "rule_type": "skill_slot_cost_delta_power",
            "base_energy_cost": skill.base_energy_cost,
            "current_energy_cost": current_cost,
            "cost_delta": delta,
            "power_add": power_add,
        }

    def _snapshot_layers_for_power_rule(
        self,
        context: DamageFormulaContext,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(context.snapshot_payload, list):
            return {"status": "unknown", "reason": "snapshot_payload_missing"}
        target = self._dynamic_power_source_target(
            context,
            str(rule.get("source_target") or "defender_side"),
        )
        if target is None:
            return {"status": "unknown", "reason": "source_target_unsupported"}
        effect_ids = self._normalize_str_set(rule.get("source_effect_ids"))
        if isinstance(rule.get("source_effect_id"), str):
            effect_ids.add(str(rule["source_effect_id"]))
        categories = self._normalize_str_set(rule.get("source_categories"))
        if isinstance(rule.get("source_category"), str):
            categories.add(str(rule["source_category"]))

        total = Decimal("0")
        matched: list[dict[str, Any]] = []
        for item in context.snapshot_payload:
            if not isinstance(item, dict):
                continue
            if effect_ids and item.get("effect_id") not in effect_ids:
                continue
            if categories and item.get("category") not in categories:
                continue
            if not effect_ids and not categories:
                continue
            if not self._snapshot_item_matches_target(item, target):
                continue
            layers = self._snapshot_layers(item)
            total += layers
            matched.append(
                {
                    "instance_id": item.get("instance_id"),
                    "effect_id": item.get("effect_id"),
                    "category": item.get("category"),
                    "owner_side": item.get("owner_side"),
                    "owner_elf_id": item.get("owner_elf_id"),
                    "layers": layers,
                }
            )
        return {"status": "resolved", "layers": total, "matched_instances": matched}

    def _state_hp_percent(
        self,
        context: DamageFormulaContext,
        *,
        target: str,
    ) -> Decimal | None:
        state = self._state_for_target(context, target)
        if state is None or state.current_hp_percent is None:
            return None
        return self._to_decimal(state.current_hp_percent)

    def _state_for_target(
        self,
        context: DamageFormulaContext,
        target: str,
    ) -> BattleElfState | None:
        if self.db is None:
            return None
        if target in {"actor", "actor_side", "attacker", "attacker_side", "self_side"}:
            side = context.attacker_side
            elf_id = context.attacker_elf_id
        elif target in {"defender", "defender_side", "enemy_side", "target", "target_side"}:
            side = context.defender_side
            elf_id = context.defender_elf_id
        else:
            return None
        if not context.battle_id or not side or not elf_id:
            return None
        return self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == context.battle_id,
                BattleElfState.side == side,
                BattleElfState.elf_id == elf_id,
            )
        ).first()

    def _condition_matches(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        condition: str,
    ) -> str:
        value = self._payload_condition_value(payload, condition)
        if value is True:
            return "matched"
        if value is False:
            return "skipped"
        if condition == "previous_turn_response_success":
            previous = self._previous_turn_response_success(context, payload)
            if previous is None:
                return "unknown"
            return "matched" if previous else "skipped"
        if condition == "any_response_success":
            for key in (
                "response_attack_success",
                "response_defense_success",
                "response_status_success",
            ):
                if self._payload_condition_value(payload, key) is True:
                    return "matched"
            return "skipped"
        if condition in {
            "self_switched_this_turn",
            "enemy_switched_this_turn",
            "enemy_normal_switched_this_turn",
            "opponent_normal_switched_this_turn",
            "target_switched_this_turn",
            "target_normal_switched_this_turn",
            "defender_switched_this_turn",
            "actor_switched_this_turn",
        }:
            switched = self._switch_condition_matches(context, payload, condition)
            if switched is None:
                return "unknown"
            return "matched" if switched else "skipped"
        return "unknown"

    @staticmethod
    def _compare_decimal(left: Decimal, operator: str, right: Decimal) -> bool | None:
        if operator in {"lte", "le", "<="}:
            return left <= right
        if operator in {"lt", "<"}:
            return left < right
        if operator in {"gte", "ge", ">="}:
            return left >= right
        if operator in {"gt", ">"}:
            return left > right
        if operator in {"eq", "=="}:
            return left == right
        if operator in {"ne", "!="}:
            return left != right
        return None

    def _previous_turn_response_success(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
    ) -> bool | None:
        if self.db is None or not context.battle_id or not context.attacker_side:
            return None
        try:
            current_turn = int(payload.get("turn_number"))
        except (TypeError, ValueError):
            return None
        if current_turn <= 1:
            return False
        events = self.db.scalars(
            select(BattleEvent).where(
                BattleEvent.battle_id == context.battle_id,
                BattleEvent.turn_number == current_turn - 1,
                BattleEvent.actor_side == context.attacker_side,
                BattleEvent.is_voided.is_(False),
            )
        ).all()
        for event in events:
            event_payload = loads_json(event.payload_json, {})
            if not isinstance(event_payload, dict):
                continue
            flags = event_payload.get("condition_flags")
            for key in (
                "response_attack_success",
                "response_defense_success",
                "response_status_success",
            ):
                if event_payload.get(key) is True:
                    return True
                if isinstance(flags, dict) and flags.get(key) is True:
                    return True
        return False

    def _switch_condition_matches(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        condition: str,
    ) -> bool | None:
        if self.db is None or not context.battle_id:
            return None
        try:
            turn_number = int(payload.get("turn_number"))
        except (TypeError, ValueError):
            return None
        switch_events = self.db.scalars(
            select(BattleEvent).where(
                BattleEvent.battle_id == context.battle_id,
                BattleEvent.turn_number == turn_number,
                BattleEvent.event_type == "switch_elf",
                BattleEvent.actor_side.is_not(None),
                BattleEvent.is_voided.is_(False),
            )
        ).all()
        switched_sides = {event.actor_side for event in switch_events if event.actor_side}
        normal_switched_sides = {
            event.actor_side
            for event in switch_events
            if event.actor_side and self._is_normal_switch_event(event)
        }
        if condition == "self_switched_this_turn":
            return "self" in switched_sides
        if condition == "enemy_switched_this_turn":
            return "enemy" in switched_sides
        if condition in {"enemy_normal_switched_this_turn", "opponent_normal_switched_this_turn"}:
            return "enemy" in normal_switched_sides
        if condition in {"target_switched_this_turn", "defender_switched_this_turn"}:
            return context.defender_side in switched_sides
        if condition == "target_normal_switched_this_turn":
            return context.defender_side in normal_switched_sides
        if condition == "actor_switched_this_turn":
            return context.attacker_side in switched_sides
        return False

    @staticmethod
    def _is_normal_switch_event(event: BattleEvent) -> bool:
        if event.source != "manual_input":
            return False
        payload = loads_json(event.payload_json, {})
        if not isinstance(payload, dict):
            return True
        return payload.get("switch_mode") not in {"forced", "return_to_field"}

    @staticmethod
    def _payload_condition_value(payload: dict[str, Any], condition: str) -> bool | None:
        manual_flags = payload.get("manual_flags")
        condition_flags = payload.get("condition_flags")
        for value in (
            payload.get(condition),
            manual_flags.get(condition) if isinstance(manual_flags, dict) else None,
            condition_flags.get(condition) if isinstance(condition_flags, dict) else None,
        ):
            if isinstance(value, bool):
                return value
        return None

    @staticmethod
    def _dynamic_power_source_target(
        context: DamageFormulaContext,
        source_target: str,
    ) -> dict[str, str | None] | None:
        if source_target in {"defender_side", "enemy_side", "target", "target_side"}:
            return {"owner_side": context.defender_side, "owner_elf_id": context.defender_elf_id}
        if source_target in {"actor_side", "attacker_side", "self_side"}:
            return {"owner_side": context.attacker_side, "owner_elf_id": context.attacker_elf_id}
        return None

    @staticmethod
    def _normalize_str_set(value: Any) -> set[str]:
        if isinstance(value, str):
            return {value}
        if isinstance(value, list):
            return {str(item) for item in value if item is not None and str(item)}
        return set()

    def _resolve_weather_multiplier(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        if "weather_multiplier" in payload:
            details["weather_multiplier"] = {
                "source": "manual_payload",
                "value": str(context.weather_multiplier),
            }
            return

        source = self._weather_source_from_snapshot(context)
        if source is None:
            return

        context.weather_multiplier = source["multiplier"]
        details["weather_multiplier"] = {
            "source": source["source"],
            "effect_id": source["effect_id"],
            "effect_name": source["effect_name"],
            "skill_element_type": context.skill_element_type,
            "matched_element_type": source.get("matched_element_type"),
            "value": str(source["multiplier"]),
        }

    def _resolve_stat_stage_multiplier(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        """从快照状态解析攻击/防御百分比修正，形成能力等级倍率。"""
        if "stat_stage_multiplier" in payload:
            details["stat_stage_multiplier"] = {
                "source": "manual_payload",
                "value": str(context.stat_stage_multiplier),
            }
            return
        if self.db is None or not isinstance(context.snapshot_payload, list):
            return
        stat_pair = self._stat_pair_for_skill_category(context.skill_category)
        if stat_pair is None:
            return

        attack_stat, defense_stat = stat_pair
        attack_up = Decimal("0")
        attack_down = Decimal("0")
        defense_up = Decimal("0")
        defense_down = Decimal("0")
        items: list[dict[str, Any]] = []

        for item in context.snapshot_payload:
            if not isinstance(item, dict):
                continue
            effect_id = item.get("effect_id")
            if not effect_id:
                continue
            definition = self.db.get(EffectDefinition, str(effect_id))
            if definition is None or definition.deleted_at is not None:
                continue
            rule = loads_json(definition.stat_modifier_json, {})
            layers = self._snapshot_layers(item)
            for modifier in self._iter_stat_modifiers(rule):
                stat = modifier.get("stat")
                value = self._stat_modifier_value(modifier, layers)
                if value is None or stat not in {attack_stat, defense_stat}:
                    continue
                role = self._snapshot_stat_modifier_role(context, item)
                if role is None:
                    continue
                if role == "attacker" and stat == attack_stat:
                    if value >= 0:
                        attack_up += value
                    else:
                        attack_down += abs(value)
                elif role == "defender" and stat == defense_stat:
                    if value >= 0:
                        defense_up += value
                    else:
                        defense_down += abs(value)
                else:
                    continue
                items.append(
                    {
                        "effect_id": str(effect_id),
                        "effect_name": definition.effect_name,
                        "role": role,
                        "stat": stat,
                        "layers": str(layers),
                        "value": str(value),
                    }
                )

        if not items:
            return
        numerator = Decimal("1") + attack_up + defense_down
        denominator = Decimal("1") + attack_down + defense_up
        context.stat_stage_multiplier = numerator / denominator
        details["stat_stage_multiplier"] = {
            "source": "snapshot_stat_modifiers",
            "attack_stat": attack_stat,
            "defense_stat": defense_stat,
            "attack_up": str(attack_up),
            "attack_down": str(attack_down),
            "defense_up": str(defense_up),
            "defense_down": str(defense_down),
            "value": str(context.stat_stage_multiplier),
            "items": items,
        }

    def _resolve_damage_reductions(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        """解析结构化减伤来源为公式可消费的 reduction 列表。"""
        if "damage_reductions" in payload:
            details["damage_reductions"] = {
                "source": "manual_payload",
                "value": [str(item) for item in context.damage_reductions],
            }
            return

        sources = self._damage_reduction_sources(context, payload)
        if not sources:
            return

        reductions: list[Decimal] = []
        normalized_sources: list[dict[str, Any]] = []
        for index, item in enumerate(sources):
            if not isinstance(item, dict):
                context.unknown_factors.append(f"damage_reduction_source_invalid:{index}")
                continue

            active = self._source_active(item, payload)
            if active is None:
                context.unknown_factors.append(f"damage_reduction_active_unknown:{index}")
                continue
            if not active:
                continue

            reduction = item.get("reduction")
            if reduction is None:
                reduction = item.get("damage_reduction")
            if reduction is None and item.get("multiplier") is not None:
                reduction = Decimal("1") - self._to_decimal(item["multiplier"])
            if reduction is None:
                context.unknown_factors.append(f"damage_reduction_value_missing:{index}")
                continue

            decimal_reduction = self._normalize_reduction(reduction)
            if decimal_reduction is None:
                context.unknown_factors.append(f"damage_reduction_value_invalid:{index}")
                continue
            dynamic_detail = self._resolve_dynamic_damage_reduction(context, item, index)
            if dynamic_detail is not None:
                if dynamic_detail["status"] == "resolved":
                    decimal_reduction += dynamic_detail["bonus_reduction"]
                    if decimal_reduction > Decimal("1"):
                        decimal_reduction = Decimal("1")
                        dynamic_detail["capped"] = True
                    else:
                        dynamic_detail["capped"] = False
                elif dynamic_detail["status"] == "unknown":
                    context.unknown_factors.append(
                        f"dynamic_damage_reduction_unknown:{index}:{dynamic_detail['reason']}"
                    )
            reductions.append(decimal_reduction)
            normalized_source = {
                "source_id": item.get("source_id") or item.get("skill_id") or item.get("effect_id"),
                "source_type": item.get("source_type"),
                "reduction": str(decimal_reduction),
                "certainty": item.get("certainty", "known"),
            }
            if dynamic_detail is not None:
                normalized_source["dynamic_reduction"] = self._stringify_detail(dynamic_detail)
            normalized_sources.append(normalized_source)

        context.damage_reductions = reductions
        details["damage_reductions"] = {
            "source": "modifier_resolver",
            "items": normalized_sources,
        }

    def _damage_reduction_sources(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        raw_sources = payload.get("damage_reduction_sources") or []
        if isinstance(raw_sources, list):
            sources.extend(item for item in raw_sources if isinstance(item, dict))

        for key in ("defense_skill_rule", "defense_rule"):
            source = self._source_from_rule(payload.get(key), payload.get("defense_skill_id"))
            if source is not None:
                sources.append(source)

        source = self._source_from_defense_skill_id(payload.get("defense_skill_id"))
        if source is not None:
            sources.append(source)

        sources.extend(self._sources_from_snapshot(context))
        return sources

    def _source_from_defense_skill_id(self, skill_id: Any) -> dict[str, Any] | None:
        if self.db is None or not skill_id:
            return None
        skill = self.db.get(SkillDefinition, str(skill_id))
        if skill is None or skill.deleted_at is not None:
            return None
        rule = loads_json(skill.damage_rule_json, {})
        source = self._source_from_rule(rule, skill.skill_id)
        if source is not None:
            source.setdefault("source_type", "defense_skill")
            source.setdefault("source_name", skill.skill_name)
        return source

    def _sources_from_snapshot(self, context: DamageFormulaContext) -> list[dict[str, Any]]:
        if self.db is None or not isinstance(context.snapshot_payload, list):
            return []
        sources: list[dict[str, Any]] = []
        for item in context.snapshot_payload:
            if not isinstance(item, dict) or not self._snapshot_item_applies(context, item):
                continue
            effect_id = item.get("effect_id")
            if not effect_id:
                continue
            definition = self.db.get(EffectDefinition, str(effect_id))
            if definition is None or definition.deleted_at is not None:
                continue
            for raw_rule in (
                loads_json(definition.damage_modifier_json, {}),
                loads_json(definition.resource_modifier_json, {}),
            ):
                source = self._source_from_rule(raw_rule, str(effect_id))
                if source is None:
                    continue
                source.setdefault("source_type", "effect_snapshot")
                source.setdefault("effect_instance_id", item.get("instance_id"))
                source.setdefault("layers", item.get("layers"))
                sources.append(source)
        return sources

    def _weather_source_from_snapshot(
        self,
        context: DamageFormulaContext,
    ) -> dict[str, Any] | None:
        if self.db is None or not isinstance(context.snapshot_payload, list):
            return None
        for item in context.snapshot_payload:
            if not isinstance(item, dict) or item.get("owner_scope") != "field":
                continue
            effect_id = item.get("effect_id")
            if not effect_id:
                continue
            definition = self.db.get(EffectDefinition, str(effect_id))
            if (
                definition is None
                or definition.deleted_at is not None
                or definition.category != "weather"
            ):
                continue
            skill_rule = loads_json(definition.skill_modifier_json, {})
            if not isinstance(skill_rule, dict) or not skill_rule:
                formula_hooks = loads_json(definition.formula_hooks_json, [])
                if (
                    isinstance(formula_hooks, list)
                    and "weather_damage_bonus" in formula_hooks
                ):
                    return None
                return {
                    "source": "weather_effect_no_damage_bonus",
                    "effect_id": definition.effect_id,
                    "effect_name": definition.effect_name,
                    "multiplier": Decimal("1"),
                }
            source = self._weather_source_from_skill_rule(
                skill_rule,
                definition,
                context.skill_element_type,
            )
            if source is not None:
                return source
        return None

    def _weather_source_from_skill_rule(
        self,
        rule: dict[str, Any],
        definition: EffectDefinition,
        skill_element_type: str | None,
    ) -> dict[str, Any] | None:
        if rule.get("modifier_type") != "damage_bonus":
            return {
                "source": "weather_effect_no_attack_damage_bonus",
                "effect_id": definition.effect_id,
                "effect_name": definition.effect_name,
                "multiplier": Decimal("1"),
            }
        rule_element_type = rule.get("element_type")
        if rule_element_type and not element_type_matches(rule_element_type, skill_element_type):
            return {
                "source": "weather_damage_bonus_not_matched",
                "effect_id": definition.effect_id,
                "effect_name": definition.effect_name,
                "matched_element_type": str(rule_element_type),
                "multiplier": Decimal("1"),
            }

        value = self._to_decimal(rule.get("value", "0"))
        value_type = str(rule.get("value_type") or "")
        if value_type in {"percent_add", "add_percent"}:
            multiplier = Decimal("1") + value
        elif value_type in {"multiplier", "damage_multiplier"}:
            multiplier = value
        else:
            return None
        return {
            "source": "weather_skill_modifier",
            "effect_id": definition.effect_id,
            "effect_name": definition.effect_name,
            "matched_element_type": str(rule_element_type) if rule_element_type else None,
            "multiplier": multiplier,
        }

    def _snapshot_item_applies(
        self,
        context: DamageFormulaContext,
        item: dict[str, Any],
    ) -> bool:
        owner_scope = item.get("owner_scope")
        owner_side = item.get("owner_side")
        owner_elf_id = item.get("owner_elf_id")
        if owner_scope == "field":
            return True
        if owner_scope == "side":
            return owner_side == context.defender_side
        if owner_scope == "elf":
            if owner_side != context.defender_side:
                return False
            return context.defender_elf_id is None or owner_elf_id == context.defender_elf_id
        return False

    @staticmethod
    def _snapshot_stat_modifier_role(
        context: DamageFormulaContext,
        item: dict[str, Any],
    ) -> str | None:
        owner_scope = item.get("owner_scope")
        owner_side = item.get("owner_side")
        owner_elf_id = item.get("owner_elf_id")
        if owner_scope == "side":
            if owner_side == context.attacker_side:
                return "attacker"
            if owner_side == context.defender_side:
                return "defender"
            return None
        if owner_scope == "elf":
            if owner_side == context.attacker_side and (
                context.attacker_elf_id is None or owner_elf_id == context.attacker_elf_id
            ):
                return "attacker"
            if owner_side == context.defender_side and (
                context.defender_elf_id is None or owner_elf_id == context.defender_elf_id
            ):
                return "defender"
        return None

    @staticmethod
    def _stat_pair_for_skill_category(skill_category: str | None) -> tuple[str, str] | None:
        if skill_category == "physical":
            return "physical_attack", "physical_defense"
        if skill_category == "magic":
            return "magic_attack", "magic_defense"
        return None

    @staticmethod
    def _iter_stat_modifiers(rule: Any) -> list[dict[str, Any]]:
        if not isinstance(rule, dict):
            return []
        modifiers = rule.get("modifiers")
        if isinstance(modifiers, list):
            return [item for item in modifiers if isinstance(item, dict)]
        if rule.get("stat") is not None:
            return [rule]
        return []

    @staticmethod
    def _source_from_rule(rule: Any, source_id: Any = None) -> dict[str, Any] | None:
        if not isinstance(rule, dict):
            return None
        reduction = rule.get("damage_reduction")
        if reduction is None:
            reduction = rule.get("reduction")
        if reduction is None and rule.get("damage_multiplier") is not None:
            reduction = Decimal("1") - Decimal(str(rule["damage_multiplier"]))
        if reduction is None and rule.get("multiplier") is not None:
            reduction = Decimal("1") - Decimal(str(rule["multiplier"]))
        if reduction is None:
            return None

        raw_response_rule = rule.get("response_rule")
        response_rule = raw_response_rule if isinstance(raw_response_rule, dict) else {}
        condition = rule.get("condition") or response_rule.get("condition")
        response_target = response_rule.get("target") or response_rule.get("response_target")
        if condition is None and response_target in {"attack", "defense", "status"}:
            condition = f"response_{response_target}_success"

        return {
            "source_id": source_id or rule.get("source_id") or rule.get("skill_id"),
            "source_type": rule.get("source_type") or rule.get("damage_type"),
            "reduction": reduction,
            "active": rule.get("active", True),
            "condition": condition,
            "response_target": response_target,
            "certainty": rule.get("certainty", "known"),
            "raw_description": rule.get("raw_description"),
            "dynamic_reduction_rule": rule.get("dynamic_reduction_rule"),
        }

    def _resolve_dynamic_damage_reduction(
        self,
        context: DamageFormulaContext,
        source: dict[str, Any],
        index: int,
    ) -> dict[str, Any] | None:
        """解析“按目标状态层数追加减伤”的防御技能分支。"""
        raw_rule = source.get("dynamic_reduction_rule")
        if not isinstance(raw_rule, dict):
            return None
        source_effect_id = raw_rule.get("source_effect_id")
        if not isinstance(source_effect_id, str) or not source_effect_id:
            return {"status": "unknown", "reason": "source_effect_id_missing"}

        per_layer = self._normalize_reduction(raw_rule.get("damage_reduction_per_layer"))
        if per_layer is None:
            return {"status": "unknown", "reason": "damage_reduction_per_layer_invalid"}

        layer_result = self._snapshot_layers_for_dynamic_rule(
            context,
            source_effect_id=source_effect_id,
            source_target=str(raw_rule.get("source_target") or "attacker_active_elf"),
        )
        if layer_result["status"] != "resolved":
            return {
                "status": layer_result["status"],
                "reason": layer_result["reason"],
                "source_effect_id": source_effect_id,
                "source_target": raw_rule.get("source_target"),
            }

        layers = layer_result["layers"]
        bonus = per_layer * layers
        return {
            "status": "resolved",
            "source_effect_id": source_effect_id,
            "source_target": raw_rule.get("source_target"),
            "source_index": index,
            "layers": layers,
            "damage_reduction_per_layer": per_layer,
            "bonus_reduction": bonus,
            "matched_instances": layer_result["matched_instances"],
        }

    def _snapshot_layers_for_dynamic_rule(
        self,
        context: DamageFormulaContext,
        *,
        source_effect_id: str,
        source_target: str,
    ) -> dict[str, Any]:
        """从历史快照中读取动态规则指定目标的状态层数。"""
        if not isinstance(context.snapshot_payload, list):
            return {"status": "unknown", "reason": "snapshot_payload_missing"}
        target = self._dynamic_source_target(context, source_target)
        if target is None:
            return {"status": "unknown", "reason": "source_target_unsupported"}

        total_layers = Decimal("0")
        matched_instances: list[dict[str, Any]] = []
        for item in context.snapshot_payload:
            if not isinstance(item, dict) or item.get("effect_id") != source_effect_id:
                continue
            if not self._snapshot_item_matches_target(item, target):
                continue
            layers = self._snapshot_layers(item)
            total_layers += layers
            matched_instances.append(
                {
                    "instance_id": item.get("instance_id"),
                    "owner_scope": item.get("owner_scope"),
                    "owner_side": item.get("owner_side"),
                    "owner_elf_id": item.get("owner_elf_id"),
                    "layers": layers,
                }
            )
        return {
            "status": "resolved",
            "layers": total_layers,
            "matched_instances": matched_instances,
        }

    @staticmethod
    def _dynamic_source_target(
        context: DamageFormulaContext,
        source_target: str,
    ) -> dict[str, str | None] | None:
        if source_target in {
            "opponent_active_elf",
            "attacker_active_elf",
            "attack_source_active_elf",
        }:
            return {
                "owner_side": context.attacker_side,
                "owner_elf_id": context.attacker_elf_id,
            }
        if source_target in {
            "self_active_elf",
            "defender_active_elf",
            "defense_owner_active_elf",
        }:
            return {
                "owner_side": context.defender_side,
                "owner_elf_id": context.defender_elf_id,
            }
        return None

    @staticmethod
    def _snapshot_item_matches_target(
        item: dict[str, Any],
        target: dict[str, str | None],
    ) -> bool:
        owner_scope = item.get("owner_scope")
        owner_side = item.get("owner_side")
        owner_elf_id = item.get("owner_elf_id")
        target_side = target.get("owner_side")
        target_elf_id = target.get("owner_elf_id")
        if owner_scope == "field":
            return True
        if owner_side != target_side:
            return False
        if owner_scope == "side":
            return True
        if owner_scope == "elf":
            return target_elf_id is None or owner_elf_id == target_elf_id
        return False

    @staticmethod
    def _stringify_detail(value: Any) -> Any:
        """把 Decimal 细节转成字符串，便于写入 evidence/JSON。"""
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {
                str(key): ModifierResolver._stringify_detail(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [ModifierResolver._stringify_detail(item) for item in value]
        return value

    @staticmethod
    def _source_active(item: dict[str, Any], payload: dict[str, Any]) -> bool | None:
        condition = item.get("condition")
        if isinstance(condition, str) and condition:
            if condition in payload:
                return ModifierResolver._payload_bool(payload[condition])
            return None
        active = item.get("active", True)
        if active is None:
            return None
        return ModifierResolver._payload_bool(active)

    @staticmethod
    def _normalize_reduction(value: Any) -> Decimal | None:
        reduction = ModifierResolver._to_decimal(value)
        if reduction > Decimal("1") and reduction <= Decimal("100"):
            reduction = reduction / Decimal("100")
        if reduction < Decimal("0") or reduction > Decimal("1"):
            return None
        return reduction

    @staticmethod
    def _stat_modifier_value(modifier: dict[str, Any], layers: Decimal) -> Decimal | None:
        """解析属性修正：新规则按每层数值，旧规则按直写 value。"""
        if modifier.get("value_per_layer") is not None:
            per_layer = ModifierResolver._normalize_percent_modifier(
                modifier.get("value_per_layer")
            )
            return per_layer * layers if per_layer is not None else None
        return ModifierResolver._normalize_percent_modifier(modifier.get("value"))

    @staticmethod
    def _snapshot_layers(item: dict[str, Any]) -> Decimal:
        try:
            return Decimal(str(item.get("layers", 1)))
        except Exception:
            return Decimal("1")

    @staticmethod
    def _normalize_percent_modifier(value: Any) -> Decimal | None:
        if value is None:
            return None
        normalized = ModifierResolver._to_decimal(value)
        if abs(normalized) > Decimal("1") and abs(normalized) <= Decimal("100"):
            normalized = normalized / Decimal("100")
        return normalized

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _payload_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)
