"""公式修正项解析器。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.calculation.formula_context import DamageFormulaContext
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
        return details

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
            reductions.append(decimal_reduction)
            normalized_sources.append(
                {
                    "source_id": item.get("source_id") or item.get("skill_id")
                    or item.get("effect_id"),
                    "source_type": item.get("source_type"),
                    "reduction": str(decimal_reduction),
                    "certainty": item.get("certainty", "known"),
                }
            )

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
        if rule_element_type and skill_element_type != str(rule_element_type):
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
        }

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
