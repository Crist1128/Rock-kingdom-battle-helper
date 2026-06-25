"""技能规则人工审阅批次导入器。

用于把逐条审阅后的技能规则 JSON 写入 ``skill_definition``。默认 dry-run，
只有显式传入 ``--commit`` 才提交数据库事务，避免未确认规则污染计算链。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models.static import SkillDefinition
from app.utils.json import dumps_json, loads_json

REVIEW_STATUS_VALUES = {"unreviewed", "structured", "partial", "needs_review", "ambiguous"}


def read_review_rows(path: str | Path) -> list[dict[str, Any]]:
    """读取技能审阅批次 JSON。"""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("技能审阅 JSON 顶层必须是数组")
    return rows


def validate_review_rows(rows: list[dict[str, Any]]) -> list[str]:
    """校验技能审阅行，返回错误列表。"""
    errors: list[str] = []
    seen_skill_keys: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"row[{index}] 不是对象")
            continue
        skill_id = row.get("skill_id")
        skill_name = row.get("skill_name")
        skill_key = str(skill_id or skill_name or "")
        if not skill_key:
            errors.append(f"row[{index}] 缺少 skill_id 或 skill_name")
        elif skill_key in seen_skill_keys:
            errors.append(f"row[{index}] skill_id/skill_name 重复：{skill_key}")
        else:
            seen_skill_keys.add(skill_key)

        status = row.get("review_status")
        if status not in REVIEW_STATUS_VALUES:
            errors.append(f"row[{index}] {skill_id or '<missing>'} review_status 无效：{status}")

        if "damage_rule" in row and row["damage_rule"] is not None:
            if not isinstance(row["damage_rule"], dict):
                errors.append(
                    f"row[{index}] {skill_id or '<missing>'} damage_rule 必须是对象或 null"
                )
        if "hit_rule" in row and row["hit_rule"] is not None:
            if not isinstance(row["hit_rule"], dict):
                errors.append(f"row[{index}] {skill_id or '<missing>'} hit_rule 必须是对象或 null")
        if "effect_operations" in row and row["effect_operations"] is not None:
            if not isinstance(row["effect_operations"], list):
                errors.append(
                    f"row[{index}] {skill_id or '<missing>'} effect_operations 必须是数组或 null"
                )
        if "future_hooks" in row and row["future_hooks"] is not None:
            if not isinstance(row["future_hooks"], list):
                errors.append(f"row[{index}] {skill_id or '<missing>'} future_hooks 必须是数组")
    return errors


def import_skill_rule_reviews(db: Session, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """导入技能规则审阅结果，调用方决定 commit/rollback。"""
    errors = validate_review_rows(rows)
    summary: dict[str, Any] = {
        "skills_updated": 0,
        "skills_missing": 0,
        "skills_skipped": 0,
        "errors": errors,
        "missing_skill_ids": [],
        "skill_name_fallbacks": [],
        "skill_name_conflicts": [],
        "status_counts": {},
        "structure_gap_counts": {},
        "total_rows": len(rows),
    }
    if errors:
        summary["skills_skipped"] = len(rows)
        return summary

    status_counts: Counter[str] = Counter()
    gap_counts: Counter[str] = Counter()
    for row in rows:
        skill_id = str(row.get("skill_id") or "")
        expected_name = str(row.get("skill_name") or "")
        skill = db.get(SkillDefinition, skill_id) if skill_id else None
        if skill is None or skill.deleted_at is not None:
            fallback = _find_active_skill_by_name(db, expected_name) if expected_name else None
            if fallback is not None:
                skill = fallback
                summary["skill_name_fallbacks"].append(
                    {
                        "review_skill_id": skill_id or None,
                        "skill_name": expected_name,
                        "matched_skill_id": skill.skill_id,
                    }
                )
            elif expected_name and _has_active_skill_name_conflict(db, expected_name):
                summary["skill_name_conflicts"].append(
                    {"review_skill_id": skill_id or None, "skill_name": expected_name}
                )
        if skill is None or skill.deleted_at is not None:
            summary["skills_missing"] += 1
            summary["missing_skill_ids"].append(skill_id or expected_name)
            continue

        if expected_name and expected_name != skill.skill_name:
            summary.setdefault("name_mismatches", []).append(
                {
                    "skill_id": skill.skill_id,
                    "expected": expected_name,
                    "actual": skill.skill_name,
                }
            )

        skill.damage_rule_json = _damage_rule_with_review(skill, row)
        if "hit_rule" in row:
            skill.hit_rule_json = _json_or_none(row["hit_rule"])
        if "effect_operations" in row:
            skill.effect_operations_json = _json_or_none(row["effect_operations"])

        status_counts[str(row["review_status"])] += 1
        for gap in row.get("structure_gaps") or []:
            if isinstance(gap, str) and gap:
                gap_counts[gap] += 1
        summary["skills_updated"] += 1

    db.flush()
    summary["status_counts"] = dict(sorted(status_counts.items()))
    summary["structure_gap_counts"] = dict(sorted(gap_counts.items()))
    return summary


def _find_active_skill_by_name(db: Session, skill_name: str) -> SkillDefinition | None:
    """按技能名兜底匹配，避免清洗器稳定 ID 规则调整后人工规则无法导入。"""
    if not skill_name:
        return None
    matches = list(
        db.scalars(
            select(SkillDefinition).where(
                SkillDefinition.skill_name == skill_name,
                SkillDefinition.deleted_at.is_(None),
            )
        ).all()
    )
    return matches[0] if len(matches) == 1 else None


def _has_active_skill_name_conflict(db: Session, skill_name: str) -> bool:
    if not skill_name:
        return False
    matches = list(
        db.scalars(
            select(SkillDefinition.skill_id).where(
                SkillDefinition.skill_name == skill_name,
                SkillDefinition.deleted_at.is_(None),
            )
        ).all()
    )
    return len(matches) > 1


def _damage_rule_with_review(skill: SkillDefinition, row: dict[str, Any]) -> str:
    if row.get("clear_damage_rule") is True:
        rule: dict[str, Any] = {}
    elif "damage_rule" in row:
        rule = row["damage_rule"] if isinstance(row["damage_rule"], dict) else {}
    else:
        existing = loads_json(skill.damage_rule_json, {})
        rule = existing if isinstance(existing, dict) else {}

    rule["manual_review"] = {
        "status": row["review_status"],
        "notes": row.get("review_notes"),
        "source": row.get("review_source") or "manual_skill_rule_batch_importer",
        "reviewed_at": row.get("reviewed_at") or "2026-06-11",
    }
    structure_gaps = row.get("structure_gaps")
    if isinstance(structure_gaps, list) and structure_gaps:
        rule["manual_review"]["structure_gaps"] = [
            str(item) for item in structure_gaps if isinstance(item, str) and item
        ]
    future_hooks = row.get("future_hooks")
    if isinstance(future_hooks, list) and future_hooks:
        rule["manual_review"]["future_hooks"] = [
            item for item in future_hooks if isinstance(item, dict)
        ]
    return dumps_json(rule)


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return dumps_json(value)


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description="导入技能规则人工审阅 JSON")
    parser.add_argument("--reviews-json", required=True, help="技能规则审阅 JSON 文件")
    parser.add_argument("--skip-init-db", action="store_true", help="跳过 init_db()")
    parser.add_argument("--commit", action="store_true", help="实际提交数据库事务；默认 dry-run")
    return parser


def main() -> None:
    """CLI 入口。"""
    args = build_parser().parse_args()
    if not args.skip_init_db:
        init_db()
    db = SessionLocal()
    try:
        rows = read_review_rows(args.reviews_json)
        summary = import_skill_rule_reviews(db, rows)
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
