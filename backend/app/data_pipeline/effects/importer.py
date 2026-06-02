"""
状态定义数据导入器。

本模块用于把人工审核后的 EffectDefinition JSON 导入数据库。默认 dry-run，
只有显式传入 --commit 才提交事务，避免状态规则尚未审阅完成时污染本地数据库。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models.static import EffectDefinition
from app.utils.json import dumps_json

EFFECT_DEFINITION_FIELDS = [
    "effect_name",
    "icon",
    "category",
    "polarity",
    "display_group",
    "display_priority",
    "owner_scope",
    "target_scope",
    "attach_target_type",
    "is_visible_icon",
    "is_recognizable_by_icon",
    "recognition_alias_json",
    "default_layers",
    "max_layers",
    "stack_rule",
    "refresh_rule",
    "duration_type",
    "default_duration_turns",
    "default_duration_uses",
    "clear_on_switch",
    "clear_by_abnormal_cleanse",
    "clear_by_stat_clear",
    "clear_by_mark_clear",
    "clear_by_weather_replace",
    "clear_by_skill_specific",
    "can_be_transferred",
    "can_be_converted",
    "can_be_inherited",
    "can_be_stolen",
    "can_be_doubled",
    "conflict_group",
    "conflict_policy",
    "formula_hooks_json",
    "stat_modifier_json",
    "damage_modifier_json",
    "skill_modifier_json",
    "action_modifier_json",
    "resource_modifier_json",
    "special_rule_id",
    "developer_notes",
    "data_version",
]

JSON_FIELDS = {
    "recognition_alias_json",
    "formula_hooks_json",
    "stat_modifier_json",
    "damage_modifier_json",
    "skill_modifier_json",
    "action_modifier_json",
    "resource_modifier_json",
}

REQUIRED_FIELDS = {
    "effect_id",
    "effect_name",
    "category",
    "polarity",
    "display_group",
    "owner_scope",
    "target_scope",
    "attach_target_type",
}


def read_effect_rows(path: str | Path) -> list[dict[str, Any]]:
    """读取状态定义 JSON。"""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("状态定义 JSON 顶层必须是数组")
    return rows


def validate_effect_rows(rows: list[dict[str, Any]]) -> list[str]:
    """校验状态定义行，返回错误列表。"""
    errors: list[str] = []
    seen_effect_ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"row[{index}] 不是对象")
            continue
        effect_id = row.get("effect_id")
        if not effect_id:
            errors.append(f"row[{index}] 缺少 effect_id")
        elif effect_id in seen_effect_ids:
            errors.append(f"row[{index}] effect_id 重复：{effect_id}")
        else:
            seen_effect_ids.add(str(effect_id))
        for field in sorted(REQUIRED_FIELDS):
            if row.get(field) in {None, ""}:
                errors.append(f"row[{index}] {effect_id or '<missing>'} 缺少必填字段：{field}")
    return errors


def import_effect_definitions(db: Session, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """导入状态定义，调用方决定 commit/rollback。"""
    errors = validate_effect_rows(rows)
    summary: dict[str, Any] = {
        "effects_created": 0,
        "effects_updated": 0,
        "effects_skipped": 0,
        "errors": errors,
        "warning_effect_ids": [],
        "total_rows": len(rows),
    }
    if errors:
        summary["effects_skipped"] = len(rows)
        return summary

    for row in rows:
        effect_id = str(row["effect_id"])
        clean_row = {
            field: _normalize_field(field, row.get(field))
            for field in EFFECT_DEFINITION_FIELDS
        }
        existing = db.get(EffectDefinition, effect_id)
        if existing is None:
            db.add(EffectDefinition(effect_id=effect_id, **clean_row))
            summary["effects_created"] += 1
        else:
            for field, value in clean_row.items():
                setattr(existing, field, value)
            existing.deleted_at = None
            summary["effects_updated"] += 1
        if "待确认" in str(row.get("developer_notes") or ""):
            summary["warning_effect_ids"].append(effect_id)
    db.flush()
    return summary


def get_effect_definition_status(db: Session) -> dict[str, Any]:
    """读取当前数据库中的状态定义导入状态，不修改数据库。"""
    active_filter = EffectDefinition.deleted_at.is_(None)
    total_effects = int(
        db.scalar(
            select(func.count()).select_from(EffectDefinition).where(active_filter)
        )
        or 0
    )
    data_versions = [
        {"data_version": version or "unknown", "count": int(count)}
        for version, count in db.execute(
            select(EffectDefinition.data_version, func.count())
            .where(active_filter)
            .group_by(EffectDefinition.data_version)
            .order_by(EffectDefinition.data_version)
        ).all()
    ]
    categories = [
        {"category": category, "count": int(count)}
        for category, count in db.execute(
            select(EffectDefinition.category, func.count())
            .where(active_filter)
            .group_by(EffectDefinition.category)
            .order_by(EffectDefinition.category)
        ).all()
    ]
    owner_scopes = [
        {"owner_scope": owner_scope, "count": int(count)}
        for owner_scope, count in db.execute(
            select(EffectDefinition.owner_scope, func.count())
            .where(active_filter)
            .group_by(EffectDefinition.owner_scope)
            .order_by(EffectDefinition.owner_scope)
        ).all()
    ]
    effect_ids = list(
        db.scalars(
            select(EffectDefinition.effect_id)
            .where(active_filter)
            .order_by(EffectDefinition.display_priority, EffectDefinition.effect_id)
        ).all()
    )
    return {
        "total_effects": total_effects,
        "data_versions": data_versions,
        "categories": categories,
        "owner_scopes": owner_scopes,
        "effect_ids": effect_ids,
        "transaction": "read_only_status",
    }


def _normalize_field(field: str, value: Any) -> Any:
    """把 JSON 字段统一序列化为数据库中的 TEXT(JSON)。"""
    if field in JSON_FIELDS and value is not None and not isinstance(value, str):
        return dumps_json(value)
    return value


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数。"""
    parser = argparse.ArgumentParser(description="导入 EffectDefinition 状态定义 JSON")
    parser.add_argument("--effects-json", required=False, help="状态定义 JSON 文件")
    parser.add_argument("--skip-init-db", action="store_true", help="跳过 init_db()")
    parser.add_argument("--commit", action="store_true", help="实际提交数据库事务；默认 dry-run")
    parser.add_argument("--status", action="store_true", help="只读取当前状态定义导入状态")
    return parser


def main() -> None:
    """CLI 入口。"""
    args = build_parser().parse_args()
    if not args.skip_init_db:
        init_db()
    db = SessionLocal()
    try:
        if args.status:
            print(json.dumps(get_effect_definition_status(db), ensure_ascii=False, indent=2))
            return
        if not args.effects_json:
            raise SystemExit("--effects-json is required unless --status is used")
        rows = read_effect_rows(args.effects_json)
        summary = import_effect_definitions(db, rows)
        if args.commit and not summary["errors"]:
            db.commit()
            summary["transaction"] = "committed"
        else:
            db.rollback()
            summary["transaction"] = "rolled_back_dry_run"
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
