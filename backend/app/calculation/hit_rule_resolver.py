"""连击规则解析器。

该模块只负责把静态技能 hit_rule_json 与事件 payload 中的手动连击输入合并到
DamageFormulaContext；真正的单段伤害和总伤害仍由 AttackDamageCalculator 计算。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculation.formula_context import DamageFormulaContext
from app.models.battle import BattleElfState
from app.models.event import BattleEvent
from app.models.static import SkillDefinition
from app.utils.json import loads_json


class HitRuleResolver:
    """解析技能固定连击数与本次事件手动连击数。"""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def resolve_hit_rule(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """把连击规则写入公式上下文，并返回可解释细节。"""
        if context.formula_type != "attack":
            return {}

        details: dict[str, Any] = {}
        skill_rule = self._load_skill_hit_rule(context.skill_id)
        payload_hit_count = self._positive_int(payload.get("hit_count"))
        combo_count_source = payload.get("combo_count_source")
        prefill_sources = {"skill_rule_prefill", "skill_hit_rule"}
        effect_prefill_hit_count = (
            payload_hit_count if combo_count_source == "auto_effect_prefill" else None
        )
        manual_hit_count = (
            payload_hit_count
            if payload_hit_count is not None
            and combo_count_source not in {*prefill_sources, "auto_effect_prefill"}
            else None
        )
        prefilled_hit_count = (
            payload_hit_count
            if manual_hit_count is None and effect_prefill_hit_count is None
            else None
        )
        skill_hit_count = self._positive_int(skill_rule.get("hit_count"))

        if payload.get("damage_display_type") is not None:
            context.damage_display_type = str(payload["damage_display_type"])
        elif skill_rule.get("damage_display_type") is not None:
            context.damage_display_type = str(skill_rule["damage_display_type"])

        if manual_hit_count is not None:
            context.hit_count = manual_hit_count
            source = "manual_payload"
        elif effect_prefill_hit_count is not None:
            context.hit_count = effect_prefill_hit_count
            source = "auto_effect_prefill"
        elif skill_hit_count is not None:
            context.hit_count = skill_hit_count
            source = "skill_hit_rule"
        elif prefilled_hit_count is not None:
            context.hit_count = prefilled_hit_count
            source = "skill_rule_prefill"
        else:
            context.hit_count = max(int(context.hit_count or 1), 1)
            source = "context_default"

        conditional_detail: dict[str, Any] = {}
        if manual_hit_count is None and effect_prefill_hit_count is None:
            conditional_detail = self._resolve_conditional_hit_rule(context, payload, skill_rule)
            if conditional_detail.get("status") == "matched":
                context.hit_count = self._apply_hit_count_delta(
                    context.hit_count,
                    conditional_detail,
                )
                source = "conditional_hit_rule"
        elif isinstance(skill_rule.get("conditional_hit_rule"), dict):
            conditional_detail = {
                "status": "skipped",
                "reason": "manual_hit_count_override",
            }

        if source != "context_default" or skill_rule:
            details["hit_rule"] = {
                "source": source,
                "hit_count": context.hit_count,
                "damage_display_type": context.damage_display_type,
                "runtime_record_strategy": skill_rule.get("runtime_record_strategy"),
                "skill_hit_count": skill_hit_count,
                "manual_hit_count": manual_hit_count,
                "prefilled_hit_count": prefilled_hit_count,
                "effect_prefill_hit_count": effect_prefill_hit_count,
            }
            if conditional_detail:
                details["hit_rule"]["conditional_hit_rule"] = conditional_detail
        return details

    def _resolve_conditional_hit_rule(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        skill_rule: dict[str, Any],
    ) -> dict[str, Any]:
        raw_rule = skill_rule.get("conditional_hit_rule")
        if not isinstance(raw_rule, dict):
            return {}

        condition = raw_rule.get("condition")
        if isinstance(condition, str) and condition:
            condition_result = self._condition_matches(context, payload, condition)
            if condition_result != "matched":
                if condition_result == "unknown":
                    context.unknown_factors.append(f"conditional_hit_rule_unknown:{condition}")
                return {
                    "status": condition_result,
                    "condition": condition,
                }

        source_effect_id = raw_rule.get("source_effect_id")
        if isinstance(source_effect_id, str) and source_effect_id:
            layer_detail = self._snapshot_layers_for_rule(context, raw_rule)
            if layer_detail["status"] != "resolved":
                context.unknown_factors.append(
                    f"conditional_hit_rule_layers_unknown:{source_effect_id}"
                )
                return {
                    "status": layer_detail["status"],
                    "condition": condition,
                    "source_effect_id": source_effect_id,
                    "reason": layer_detail.get("reason"),
                }
            layer_count = layer_detail["layers"]
            bonus_per_layer = self._decimal(raw_rule.get("hit_count_bonus_per_layer"))
            if bonus_per_layer is not None:
                hit_count_bonus = int(layer_count * bonus_per_layer)
                if hit_count_bonus <= 0:
                    return {
                        "status": "not_matched",
                        "condition": condition,
                        "source_effect_id": source_effect_id,
                        "layers": str(layer_count),
                        "reason": "hit_count_bonus_zero",
                    }
                return {
                    "status": "matched",
                    "condition": condition,
                    "source_effect_id": source_effect_id,
                    "source_target": raw_rule.get("source_target"),
                    "layers": str(layer_count),
                    "hit_count_bonus": hit_count_bonus,
                    "matched_instances": layer_detail["matched_instances"],
                }

        return {
            "status": "matched",
            "condition": condition,
            "hit_count": self._positive_int(raw_rule.get("hit_count")),
            "hit_count_bonus": self._int_value(raw_rule.get("hit_count_bonus")),
            "hit_count_multiplier": self._decimal(raw_rule.get("hit_count_multiplier")),
        }

    @staticmethod
    def _apply_hit_count_delta(current: int, detail: dict[str, Any]) -> int:
        fixed = detail.get("hit_count")
        if isinstance(fixed, int) and fixed > 0:
            return fixed
        bonus = detail.get("hit_count_bonus")
        if isinstance(bonus, int):
            return max(current + bonus, 1)
        multiplier = detail.get("hit_count_multiplier")
        if isinstance(multiplier, Decimal):
            return max(int(current * multiplier), 1)
        return max(current, 1)

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
            return "not_matched"
        if condition == "actor_hp_percent_below_50":
            hp_percent = self._actor_hp_percent(context, payload)
            if hp_percent is None:
                return "unknown"
            return "matched" if hp_percent < Decimal("50") else "not_matched"
        if condition == "any_response_success":
            for key in (
                "response_attack_success",
                "response_defense_success",
                "response_status_success",
            ):
                if self._payload_condition_value(payload, key) is True:
                    return "matched"
            return "not_matched"
        if condition in {
            "self_switched_this_turn",
            "enemy_switched_this_turn",
            "target_switched_this_turn",
            "defender_switched_this_turn",
            "actor_switched_this_turn",
        }:
            switched = self._switch_condition_matches(context, payload, condition)
            if switched is None:
                return "unknown"
            return "matched" if switched else "not_matched"
        return "unknown"

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

    def _actor_hp_percent(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
    ) -> Decimal | None:
        for key in ("actor_hp_percent", "attacker_hp_percent"):
            value = self._decimal(payload.get(key))
            if value is not None:
                return value
        if (
            self.db is None
            or not context.battle_id
            or not context.attacker_side
            or not context.attacker_elf_id
        ):
            return None
        state = self.db.scalars(
            select(BattleElfState.current_hp_percent).where(
                BattleElfState.battle_id == context.battle_id,
                BattleElfState.side == context.attacker_side,
                BattleElfState.elf_id == context.attacker_elf_id,
            )
        ).first()
        return self._decimal(state)

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
        switched_sides = {
            side
            for side in self.db.scalars(
                select(BattleEvent.actor_side).where(
                    BattleEvent.battle_id == context.battle_id,
                    BattleEvent.turn_number == turn_number,
                    BattleEvent.event_type == "switch_elf",
                    BattleEvent.actor_side.is_not(None),
                    BattleEvent.is_voided.is_(False),
                )
            ).all()
            if side
        }
        if condition == "self_switched_this_turn":
            return "self" in switched_sides
        if condition == "enemy_switched_this_turn":
            return "enemy" in switched_sides
        if condition in {"target_switched_this_turn", "defender_switched_this_turn"}:
            return context.defender_side in switched_sides
        if condition == "actor_switched_this_turn":
            return context.attacker_side in switched_sides
        return False

    def _snapshot_layers_for_rule(
        self,
        context: DamageFormulaContext,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(context.snapshot_payload, list):
            return {"status": "unknown", "reason": "snapshot_payload_missing"}
        source_effect_id = rule.get("source_effect_id")
        if not isinstance(source_effect_id, str) or not source_effect_id:
            return {"status": "unknown", "reason": "source_effect_id_missing"}
        target = self._source_target(context, str(rule.get("source_target") or "enemy_side"))
        if target is None:
            return {"status": "unknown", "reason": "source_target_unsupported"}
        layers = Decimal("0")
        matched: list[dict[str, Any]] = []
        for item in context.snapshot_payload:
            if not isinstance(item, dict) or item.get("effect_id") != source_effect_id:
                continue
            if not self._snapshot_item_matches(item, target):
                continue
            item_layers = self._decimal(item.get("layers")) or Decimal("1")
            layers += item_layers
            matched.append(
                {
                    "instance_id": item.get("instance_id"),
                    "owner_side": item.get("owner_side"),
                    "owner_elf_id": item.get("owner_elf_id"),
                    "layers": str(item_layers),
                }
            )
        return {"status": "resolved", "layers": layers, "matched_instances": matched}

    @staticmethod
    def _source_target(
        context: DamageFormulaContext,
        source_target: str,
    ) -> dict[str, str | None] | None:
        if source_target in {"enemy_side", "defender_side", "target", "target_side"}:
            return {"owner_side": context.defender_side, "owner_elf_id": context.defender_elf_id}
        if source_target in {"actor_side", "self_side", "attacker_side"}:
            return {"owner_side": context.attacker_side, "owner_elf_id": context.attacker_elf_id}
        return None

    @staticmethod
    def _snapshot_item_matches(
        item: dict[str, Any],
        target: dict[str, str | None],
    ) -> bool:
        owner_scope = item.get("owner_scope")
        if owner_scope == "field":
            return True
        if item.get("owner_side") != target.get("owner_side"):
            return False
        if owner_scope == "side":
            return True
        if owner_scope == "elf":
            target_elf_id = target.get("owner_elf_id")
            return target_elf_id is None or item.get("owner_elf_id") == target_elf_id
        return False

    def _load_skill_hit_rule(self, skill_id: str | None) -> dict[str, Any]:
        if self.db is None or not skill_id:
            return {}
        skill = self.db.get(SkillDefinition, skill_id)
        if skill is None or skill.deleted_at is not None:
            return {}
        rule = loads_json(skill.hit_rule_json, {})
        return rule if isinstance(rule, dict) else {}

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _int_value(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        try:
            return Decimal(str(value))
        except Exception:
            return None
