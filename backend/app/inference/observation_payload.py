"""Observation payload 标准化工具。

外部调用可以继续使用旧的平铺字段；新的推荐格式使用 schema_version 标记的 v1 嵌套结构。
推理层统一先归一化为当前 matcher 消费的平铺键，避免每个入口重复拆字段。
"""

from __future__ import annotations

from typing import Any

from app.inference.observation_types import ObservationType

OBSERVATION_PAYLOAD_SCHEMA_VERSION = "observation_payload_v1"


def normalize_observation_payload(
    payload: dict[str, Any] | None,
    *,
    observation_type: ObservationType | str | None = None,
    observed_value: int | float | str | None = None,
) -> dict[str, Any]:
    """把 v1 嵌套 payload 归一化为 matcher 当前消费的平铺字段。"""
    normalized = dict(payload or {})
    if not normalized:
        return normalized

    for source_key, mapping in (
        (
            "roles",
            {
                "enemy_role": "enemy_role",
            },
        ),
        (
            "participants",
            {
                "attacker_side": "attacker_side",
                "attacker_elf_id": "attacker_elf_id",
                "defender_side": "defender_side",
                "defender_elf_id": "defender_elf_id",
            },
        ),
        (
            "panels",
            {
                "attacker": "attacker_panel_stats",
                "attacker_panel_stats": "attacker_panel_stats",
                "defender": "defender_panel_stats",
                "defender_panel_stats": "defender_panel_stats",
                "defender_max_hp": "defender_max_hp",
            },
        ),
        (
            "skill",
            {
                "skill_id": "skill_id",
                "defense_skill_id": "defense_skill_id",
                "skill_category": "skill_category",
                "skill_element_type": "skill_element_type",
                "trigger_skill_id": "trigger_skill_id",
                "trigger_skill_element_type": "trigger_skill_element_type",
                "trigger_skill_category": "trigger_skill_category",
            },
        ),
        (
            "response",
            {
                "response_success": "response_success",
                "attack_success": "response_attack_success",
                "defense_success": "response_defense_success",
                "status_success": "response_status_success",
                "response_attack_success": "response_attack_success",
                "response_defense_success": "response_defense_success",
                "response_status_success": "response_status_success",
                "response_multiplier": "response_multiplier",
                "response_success_multiplier": "response_success_multiplier",
                "response_rule_multiplier": "response_rule_multiplier",
                "response_rule": "response_rule",
                "skill_response_rule": "skill_response_rule",
                "response_condition": "response_condition",
            },
        ),
        (
            "formula",
            {
                "formula_type": "formula_type",
                "resolve_rules": "resolve_rules",
                "base_power": "base_power",
                "display_power": "display_power",
                "flat_power_bonus": "flat_power_bonus",
                "power_multiplier": "power_multiplier",
                "stat_stage_multiplier": "stat_stage_multiplier",
                "stab_multiplier": "stab_multiplier",
                "type_multiplier": "type_multiplier",
                "weather_multiplier": "weather_multiplier",
                "unstable_multiplier": "unstable_multiplier",
                "hit_count": "hit_count",
            },
        ),
        (
            "modifiers",
            {
                "damage_reductions": "damage_reductions",
                "damage_reduction_sources": "damage_reduction_sources",
                "defense_skill_rule": "defense_skill_rule",
                "defense_rule": "defense_rule",
                "weather_multiplier": "weather_multiplier",
            },
        ),
        (
            "effects",
            {
                "effect_id": "effect_id",
                "effect_layers": "effect_layers",
                "starfall_element_type": "starfall_element_type",
            },
        ),
        (
            "observed",
            {
                "damage_value": "observed_damage_value",
                "observed_damage_value": "observed_damage_value",
                "hp_percent_delta": "observed_hp_percent_delta",
                "observed_hp_percent_delta": "observed_hp_percent_delta",
                "order": "observed_order",
                "observed_order": "observed_order",
            },
        ),
        (
            "matching",
            {
                "damage_tolerance": "damage_tolerance",
                "percent_tolerance": "percent_tolerance",
                "skill_pool_reliable": "skill_pool_reliable",
                "self_speed": "self_speed",
                "unknown_factors": "unknown_factors",
                "event_weight": "event_weight",
            },
        ),
        (
            "speed",
            {
                "self_speed": "self_speed",
                "observed_order": "observed_order",
                "unknown_factors": "unknown_factors",
            },
        ),
    ):
        _copy_nested_values(normalized, source_key, mapping)

    if observed_value is not None:
        _fill_observed_value(normalized, observation_type, observed_value)
    return normalized


def build_damage_observation_payload(
    *,
    formula_type: str,
    observed_damage_value: int,
    enemy_role: str = "defender",
    resolve_rules: bool = True,
    attacker_panel_stats: dict[str, Any] | None = None,
    defender_panel_stats: dict[str, Any] | None = None,
    attacker_elf_id: str | None = None,
    defender_elf_id: str | None = None,
    skill_id: str | None = None,
    defense_skill_id: str | None = None,
    response_attack_success: bool | None = None,
    response_defense_success: bool | None = None,
    response_status_success: bool | None = None,
    damage_tolerance: int | float = 0,
    hit_count: int = 1,
    effect_id: str | None = None,
    effect_layers: int | None = None,
    skill_element_type: str | None = None,
    trigger_skill_id: str | None = None,
    trigger_skill_element_type: str | None = None,
    trigger_skill_category: str | None = None,
    starfall_element_type: str | None = None,
) -> dict[str, Any]:
    """构造推荐的 v1 伤害观测 payload。"""
    return _drop_empty(
        {
            "schema_version": OBSERVATION_PAYLOAD_SCHEMA_VERSION,
            "context_kind": "damage",
            "roles": {"enemy_role": enemy_role},
            "participants": _drop_empty(
                {
                    "attacker_elf_id": attacker_elf_id,
                    "defender_elf_id": defender_elf_id,
                }
            ),
            "panels": _drop_empty(
                {
                    "attacker": attacker_panel_stats,
                    "defender": defender_panel_stats,
                }
            ),
            "skill": _drop_empty(
                {
                    "skill_id": skill_id,
                    "defense_skill_id": defense_skill_id,
                    "skill_element_type": skill_element_type,
                    "trigger_skill_id": trigger_skill_id,
                    "trigger_skill_element_type": trigger_skill_element_type,
                    "trigger_skill_category": trigger_skill_category,
                }
            ),
            "response": _drop_empty(
                {
                    "attack_success": response_attack_success,
                    "defense_success": response_defense_success,
                    "status_success": response_status_success,
                }
            ),
            "formula": _drop_empty(
                {
                    "formula_type": formula_type,
                    "resolve_rules": resolve_rules,
                    "hit_count": hit_count,
                }
            ),
            "effects": _drop_empty(
                {
                    "effect_id": effect_id,
                    "effect_layers": effect_layers,
                    "starfall_element_type": starfall_element_type,
                }
            ),
            "observed": {"damage_value": observed_damage_value},
            "matching": {"damage_tolerance": damage_tolerance},
        }
    )


def _copy_nested_values(
    payload: dict[str, Any],
    source_key: str,
    mapping: dict[str, str],
) -> None:
    source = payload.get(source_key)
    if not isinstance(source, dict):
        return
    for nested_key, flat_key in mapping.items():
        if flat_key in payload:
            continue
        value = source.get(nested_key)
        if value is not None:
            payload[flat_key] = value


def _fill_observed_value(
    payload: dict[str, Any],
    observation_type: ObservationType | str | None,
    observed_value: int | float | str,
) -> None:
    observation_type_value = (
        observation_type.value
        if isinstance(observation_type, ObservationType)
        else observation_type
    )
    if observation_type_value == ObservationType.DAMAGE_VALUE.value:
        payload.setdefault("observed_damage_value", observed_value)
    elif observation_type_value == ObservationType.HP_PERCENT_DELTA.value:
        payload.setdefault("observed_hp_percent_delta", observed_value)
    elif observation_type_value == ObservationType.SPEED_ORDER.value:
        payload.setdefault("observed_order", observed_value)
    elif observation_type_value == ObservationType.SKILL_SEEN.value:
        payload.setdefault("skill_id", observed_value)


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item is not None and item != {} and item != []
    }
