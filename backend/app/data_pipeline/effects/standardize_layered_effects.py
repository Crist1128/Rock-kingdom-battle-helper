"""统一旧固定属性状态为标准层数状态。

默认 dry-run，只输出将要改动的文件/数据库统计；传入 ``--commit`` 才会写入。
"""

from __future__ import annotations

import argparse
import copy
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

Json = dict[str, Any] | list[Any] | str | int | float | bool | None


LEGACY_EFFECT_REPLACEMENTS: dict[str, list[tuple[str, int]]] = {
    "effect_physical_attack_up_100": [("effect_physical_attack_up_layered", 10)],
    "effect_physical_attack_up_30": [("effect_physical_attack_up_layered", 3)],
    "effect_physical_attack_up_50": [("effect_physical_attack_up_layered", 5)],
    "effect_physical_attack_up_130": [("effect_physical_attack_up_layered", 13)],
    "effect_physical_attack_down_70": [("effect_physical_attack_down_layered", 7)],
    "effect_physical_attack_down_60": [("effect_physical_attack_down_layered", 6)],
    "effect_magic_attack_up_30": [("effect_magic_attack_up_layered", 3)],
    "effect_magic_attack_up_70": [("effect_magic_attack_up_layered", 7)],
    "effect_magic_attack_up_90": [("effect_magic_attack_up_layered", 9)],
    "effect_magic_attack_up_190": [("effect_magic_attack_up_layered", 19)],
    "effect_physical_defense_up_70": [("effect_physical_defense_up_layered", 7)],
    "effect_physical_defense_up_140": [("effect_physical_defense_up_layered", 14)],
    "effect_physical_defense_down_40": [("effect_physical_defense_down_layered", 4)],
    "effect_magic_defense_down_50": [("effect_magic_defense_down_layered", 5)],
    "effect_speed_up_30": [("effect_speed_up_layered", 3)],
    "effect_speed_up_80": [("effect_speed_up_layered", 8)],
    "effect_speed_up_120": [("effect_speed_up_layered", 12)],
    "effect_speed_up_160": [("effect_speed_up_layered", 16)],
    "effect_speed_down_30": [("effect_speed_down_layered", 3)],
    "effect_speed_down_60": [("effect_speed_down_layered", 6)],
    "effect_physical_magic_attack_up_140": [("effect_dual_attack_up_layered", 14)],
    "effect_dual_attack_up_120_dual_defense_down_40": [
        ("effect_dual_attack_up_layered", 12),
        ("effect_dual_defense_down_layered", 4),
    ],
    "effect_dual_attack_defense_down_100": [
        ("effect_dual_attack_down_layered", 10),
        ("effect_dual_defense_down_layered", 10),
    ],
    "effect_physical_attack_physical_defense_up_60": [
        ("effect_physical_attack_up_layered", 6),
        ("effect_physical_defense_up_layered", 6),
    ],
    "effect_dual_defense_down_60": [("effect_dual_defense_down_layered", 6)],
}

EFFECT_ID_KEYS = {
    "effect_id",
    "replace_effect_id",
    "normal_effect_id",
    "response_effect_id",
}


def _read_json(path: Path) -> Json:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Json) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _scale_layers(value: Any, factor: int) -> int:
    if isinstance(value, int):
        return value * factor
    if isinstance(value, float) and value.is_integer():
        return int(value) * factor
    return factor


def _replacement_ops(operation: dict[str, Any], key: str = "effect_id") -> list[dict[str, Any]]:
    effect_id = operation.get(key)
    if not isinstance(effect_id, str) or effect_id not in LEGACY_EFFECT_REPLACEMENTS:
        return [operation]
    replacements = LEGACY_EFFECT_REPLACEMENTS[effect_id]
    result: list[dict[str, Any]] = []
    for new_effect_id, layer_factor in replacements:
        item = copy.deepcopy(operation)
        item[key] = new_effect_id
        if key == "effect_id":
            item["layers"] = _scale_layers(item.get("layers"), layer_factor)
            for sibling_key in EFFECT_ID_KEYS - {"effect_id"}:
                _normalize_future_hook_effect_id(item, sibling_key)
        item["standardized_from_effect_id"] = effect_id
        result.append(item)
    return result


def _normalize_future_hook_effect_id(obj: dict[str, Any], key: str) -> None:
    effect_id = obj.get(key)
    if not isinstance(effect_id, str) or effect_id not in LEGACY_EFFECT_REPLACEMENTS:
        return
    replacements = LEGACY_EFFECT_REPLACEMENTS[effect_id]
    if len(replacements) == 1:
        obj[key] = replacements[0][0]
        obj[f"{key}_layers"] = replacements[0][1]
        obj[f"{key}_standardized_from"] = effect_id
        return

    prefix = key.removesuffix("effect_id")
    target = obj.get(f"{prefix}target") or obj.get("target") or "actor_side"
    obj[f"{prefix}effect_operations"] = [
        {
            "op_type": "apply_effect",
            "effect_id": new_effect_id,
            "target": target,
            "layers": layers,
            "standardized_from_effect_id": effect_id,
        }
        for new_effect_id, layers in replacements
    ]
    obj[f"{key}_standardized_from"] = effect_id
    obj.pop(key, None)


def standardize_json_value(value: Json) -> Json:
    """递归替换 JSON 中的旧固定状态引用。"""
    if isinstance(value, list):
        normalized: list[Any] = []
        for item in value:
            has_legacy_effect_id = (
                isinstance(item, dict)
                and isinstance(item.get("effect_id"), str)
                and item["effect_id"] in LEGACY_EFFECT_REPLACEMENTS
            )
            if has_legacy_effect_id:
                base = {
                    key: (child if key == "effect_id" else standardize_json_value(child))
                    for key, child in item.items()
                }
                normalized.extend(_replacement_ops(base))
            else:
                normalized.append(standardize_json_value(item))
        return normalized
    if isinstance(value, dict):
        obj = {key: standardize_json_value(child) for key, child in value.items()}
        if isinstance(obj.get("effect_id"), str) and obj["effect_id"] in LEGACY_EFFECT_REPLACEMENTS:
            # 单个 operation 对象由上一层 list 展开；非 list 场景保留第一条并标注。
            return _replacement_ops(obj)[0]
        for key in EFFECT_ID_KEYS - {"effect_id"}:
            _normalize_future_hook_effect_id(obj, key)
        return obj
    return value


def _canonical_effect_definition(effect_id: str) -> dict[str, Any]:
    label_map = {
        "effect_physical_attack_up_layered": ("物攻增加", "physical_attack", 0.1),
        "effect_physical_attack_down_layered": ("物攻降低", "physical_attack", -0.1),
        "effect_magic_attack_up_layered": ("魔攻增加", "magic_attack", 0.1),
        "effect_magic_attack_down_layered": ("魔攻降低", "magic_attack", -0.1),
        "effect_physical_defense_up_layered": ("物防增加", "physical_defense", 0.1),
        "effect_physical_defense_down_layered": ("物防降低", "physical_defense", -0.1),
        "effect_magic_defense_up_layered": ("魔防增加", "magic_defense", 0.1),
        "effect_magic_defense_down_layered": ("魔防降低", "magic_defense", -0.1),
        "effect_speed_up_layered": ("速度增加", "speed", 10),
        "effect_speed_down_layered": ("速度降低", "speed", -10),
    }
    dual_map = {
        "effect_dual_attack_up_layered": (
            "双攻增加",
            [("physical_attack", 0.1), ("magic_attack", 0.1)],
        ),
        "effect_dual_attack_down_layered": (
            "双攻降低",
            [("physical_attack", -0.1), ("magic_attack", -0.1)],
        ),
        "effect_dual_defense_up_layered": (
            "双防增加",
            [("physical_defense", 0.1), ("magic_defense", 0.1)],
        ),
        "effect_dual_defense_down_layered": (
            "双防降低",
            [("physical_defense", -0.1), ("magic_defense", -0.1)],
        ),
    }
    if effect_id in label_map:
        name, stat, value = label_map[effect_id]
        value_type = "flat_add" if stat == "speed" else "percent_add"
        modifier_type = "flat_speed" if stat == "speed" else "stat_stage"
        modifiers = [
            {
                "modifier_type": modifier_type,
                "stat": stat,
                "value_type": value_type,
                "value_per_layer": value,
            }
        ]
    else:
        name, pairs = dual_map[effect_id]
        modifiers = [
            {
                "modifier_type": "stat_stage",
                "stat": stat,
                "value_type": "percent_add",
                "value_per_layer": value,
            }
            for stat, value in pairs
        ]
    return {
        "effect_id": effect_id,
        "effect_name": name,
        "icon": None,
        "category": "stat_modifier",
        "polarity": "positive" if "up" in effect_id else "negative",
        "display_group": "stat_modifier_layered",
        "display_priority": 300,
        "owner_scope": "elf",
        "target_scope": "single",
        "attach_target_type": "elf",
        "is_visible_icon": True,
        "is_recognizable_by_icon": True,
        "recognition_alias_json": [name],
        "default_layers": 1,
        "max_layers": None,
        "stack_rule": "add_layers",
        "refresh_rule": "keep_duration",
        "duration_type": "until_switch_or_cleanse",
        "default_duration_turns": None,
        "default_duration_uses": None,
        "clear_on_switch": True,
        "clear_by_abnormal_cleanse": False,
        "clear_by_stat_clear": True,
        "clear_by_mark_clear": False,
        "clear_by_weather_replace": False,
        "clear_by_skill_specific": True,
        "can_be_transferred": True,
        "can_be_converted": True,
        "can_be_inherited": False,
        "can_be_stolen": True,
        "can_be_doubled": True,
        "conflict_group": None,
        "conflict_policy": None,
        "formula_hooks_json": ["stat_modifier"],
        "stat_modifier_json": {"modifier_type": "stat_stage", "modifiers": modifiers},
        "damage_modifier_json": None,
        "skill_modifier_json": None,
        "action_modifier_json": None,
        "resource_modifier_json": None,
        "special_rule_id": None,
        "developer_notes": "标准层数状态：属性百分比每层 10%，速度每层 10 点。",
        "data_version": "manual_layered_standard_20260613",
    }


CANONICAL_EFFECT_IDS = sorted(
    {
        new_effect_id
        for replacements in LEGACY_EFFECT_REPLACEMENTS.values()
        for new_effect_id, _ in replacements
    }
)


def standardize_effect_definition_rows(
    rows: list[dict[str, Any]],
    *,
    add_missing_canonical: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """删除旧固定状态定义，补齐标准层数定义。"""
    removed = [
        row["effect_id"]
        for row in rows
        if row.get("effect_id") in LEGACY_EFFECT_REPLACEMENTS
    ]
    kept = [row for row in rows if row.get("effect_id") not in LEGACY_EFFECT_REPLACEMENTS]
    by_id = {str(row["effect_id"]): row for row in kept if row.get("effect_id")}
    added = []
    if add_missing_canonical:
        for effect_id in CANONICAL_EFFECT_IDS:
            if effect_id not in by_id:
                by_id[effect_id] = _canonical_effect_definition(effect_id)
                added.append(effect_id)
    ordered = list(by_id.values())
    return ordered, {"legacy_definitions_removed": removed, "canonical_definitions_added": added}


def _json_column_standardized(text: str | None) -> tuple[str | None, bool]:
    if not text:
        return text, False
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return text, False
    normalized = standardize_json_value(value)
    changed = normalized != value
    if not changed:
        return text, False
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")), True


def standardize_seed_files(seed_dir: Path, commit: bool) -> dict[str, Any]:
    files = sorted(seed_dir.glob("*.json"))
    summary: dict[str, Any] = {
        "json_files_scanned": len(files),
        "json_files_changed": [],
        "effect_definition_changes": {},
    }
    for path in files:
        if path.name == "manual_skill_rules_consolidation_report_20260612.json":
            continue
        try:
            original = _read_json(path)
        except Exception:
            continue
        normalized = original
        if isinstance(original, list) and all(isinstance(item, dict) for item in original):
            is_effect_definition_file = (
                path.name.startswith("manual_skill_effect_definitions")
                or path.name == "effect_definitions_p0.json"
            )
            if is_effect_definition_file:
                has_legacy_definitions = any(
                    item.get("effect_id") in LEGACY_EFFECT_REPLACEMENTS
                    for item in original
                    if isinstance(item, dict)
                )
                normalized, effect_summary = standardize_effect_definition_rows(
                    original,
                    add_missing_canonical=(
                        path.name == "effect_definitions_p0.json"
                        or "_all_" in path.name
                        or has_legacy_definitions
                    ),
                )
                if (
                    effect_summary["legacy_definitions_removed"]
                    or effect_summary["canonical_definitions_added"]
                ):
                    summary["effect_definition_changes"][path.name] = effect_summary
            else:
                normalized = standardize_json_value(original)
        else:
            normalized = standardize_json_value(original)
        if normalized != original:
            summary["json_files_changed"].append(path.name)
            if commit:
                _write_json(path, normalized)
    return summary


def standardize_database(db_path: Path, commit: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "skill_json_columns_updated": 0,
        "battle_json_columns_updated": 0,
        "effect_instances_updated": 0,
        "effect_change_events_updated": 0,
        "legacy_effect_definitions_soft_deleted": 0,
    }
    if not db_path.exists():
        summary["skipped"] = f"database not found: {db_path}"
        return summary

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        con.execute("begin")
        for table, id_col, columns in [
            (
                "skill_definition",
                "skill_id",
                ["damage_rule_json", "hit_rule_json", "effect_operations_json"],
            ),
            ("battle_event", "event_id", ["payload_json"]),
            ("battle_effect_snapshot", "snapshot_id", ["full_snapshot_json"]),
        ]:
            sql = f"select {id_col}, {', '.join(columns)} from {table}"
            for row in con.execute(sql).fetchall():
                updates = {}
                for column in columns:
                    normalized, changed = _json_column_standardized(row[column])
                    if changed:
                        updates[column] = normalized
                if updates:
                    assignments = ", ".join(f"{column}=?" for column in updates)
                    con.execute(
                        f"update {table} set {assignments} where {id_col}=?",
                        [*updates.values(), row[id_col]],
                    )
                    if table == "skill_definition":
                        summary["skill_json_columns_updated"] += 1
                    else:
                        summary["battle_json_columns_updated"] += 1

        for old_effect_id, replacements in LEGACY_EFFECT_REPLACEMENTS.items():
            if len(replacements) != 1:
                continue
            new_effect_id, factor = replacements[0]
            cur = con.execute(
                """
                update battle_effect_instance
                set effect_id=?, layers=layers * ?
                where effect_id=?
                """,
                (new_effect_id, factor, old_effect_id),
            )
            summary["effect_instances_updated"] += cur.rowcount
            cur = con.execute(
                """
                update effect_change_event
                set effect_id=?,
                    effect_name=(select effect_name from effect_definition where effect_id=?),
                    layers_before=case
                        when layers_before is null then null
                        else layers_before * ?
                    end,
                    layers_after=case
                        when layers_after is null then null
                        else layers_after * ?
                    end
                where effect_id=?
                """,
                (new_effect_id, new_effect_id, factor, factor, old_effect_id),
            )
            summary["effect_change_events_updated"] += cur.rowcount

        deleted_at = datetime.now(UTC).isoformat()
        cur = con.execute(
            f"""
            update effect_definition
            set deleted_at=?
            where effect_id in ({",".join("?" for _ in LEGACY_EFFECT_REPLACEMENTS)})
              and deleted_at is null
            """,
            [deleted_at, *LEGACY_EFFECT_REPLACEMENTS.keys()],
        )
        summary["legacy_effect_definitions_soft_deleted"] = cur.rowcount

        if commit:
            con.commit()
        else:
            con.rollback()
            summary["transaction"] = "rolled_back_dry_run"
            return summary
        summary["transaction"] = "committed"
        return summary
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一旧固定属性状态为标准层数状态")
    parser.add_argument("--seed-dir", default="backend/app/seed")
    parser.add_argument("--db-path", default="data/app.db")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--skip-seeds", action="store_true")
    parser.add_argument("--skip-db", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary: dict[str, Any] = {"commit": args.commit}
    if not args.skip_seeds:
        summary["seeds"] = standardize_seed_files(Path(args.seed_dir), args.commit)
    if not args.skip_db:
        summary["database"] = standardize_database(Path(args.db_path), args.commit)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
