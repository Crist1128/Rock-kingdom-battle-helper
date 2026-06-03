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

        return {
            "source_id": source_id or rule.get("source_id") or rule.get("skill_id"),
            "source_type": rule.get("source_type") or rule.get("damage_type"),
            "reduction": reduction,
            "active": rule.get("active", True),
            "condition": rule.get("condition"),
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
