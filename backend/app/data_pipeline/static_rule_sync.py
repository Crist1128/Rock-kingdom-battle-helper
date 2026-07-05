"""本地静态规则同步检查器。

该模块只处理已经人工审阅为 structured 的技能规则，不会触碰 partial、
needs_review 或 ambiguous 规则。检查接口默认只比较 seed 文件与数据库差异；
写库必须由调用方显式传入 commit。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.data_pipeline.skill_rule_reviews.importer import (
    _damage_rule_with_review,
    _json_or_none,
    read_review_rows,
    validate_review_rows,
)
from app.models.static import SkillDefinition
from app.utils.json import loads_json

DEFAULT_SKILL_REVIEWS_PATH = (
    Path(__file__).resolve().parents[1]
    / "seed"
    / "manual_skill_rule_reviews_all_20260612.json"
)


def check_structured_skill_rule_sync(
    db: Session,
    *,
    reviews_json: str | Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """检查 structured 技能规则 seed 与数据库是否一致，不修改数据库。"""
    rows = _read_rows(reviews_json)
    return _build_sync_plan(db, rows, limit=limit)


def sync_structured_skill_rules(
    db: Session,
    *,
    skill_ids: list[str] | None = None,
    commit: bool = False,
    reviews_json: str | Path | None = None,
) -> dict[str, Any]:
    """把选中的 structured 技能规则写入数据库；默认 dry-run。"""
    rows = _read_rows(reviews_json)
    skill_id_set = {str(item) for item in skill_ids or [] if str(item)}
    plan = _build_sync_plan(db, rows, skill_ids=skill_id_set or None)
    applied_skill_ids: set[str] = set()
    for row in _iter_structured_rows(rows):
        skill_id = str(row.get("skill_id") or "")
        if skill_id_set and skill_id not in skill_id_set:
            continue
        skill = db.get(SkillDefinition, skill_id) if skill_id else None
        if skill is None or skill.deleted_at is not None:
            continue
        desired = _desired_rule_payload(skill, row)
        if not _payload_has_difference(skill, desired):
            continue
        _apply_desired_payload(skill, desired)
        applied_skill_ids.add(skill.skill_id)
    db.flush()
    if commit:
        db.commit()
        transaction = "committed"
    else:
        db.rollback()
        transaction = "rolled_back_dry_run"
    plan["applied_skill_ids"] = sorted(applied_skill_ids)
    plan["applied_count"] = len(applied_skill_ids)
    plan["transaction"] = transaction
    return plan


def _read_rows(reviews_json: str | Path | None) -> list[dict[str, Any]]:
    path = Path(reviews_json) if reviews_json is not None else DEFAULT_SKILL_REVIEWS_PATH
    return read_review_rows(path)


def _build_sync_plan(
    db: Session,
    rows: list[dict[str, Any]],
    *,
    skill_ids: set[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    errors = validate_review_rows(rows)
    status_counts: Counter[str] = Counter(str(row.get("review_status")) for row in rows)
    structured_rows = list(_iter_structured_rows(rows))
    pending_items: list[dict[str, Any]] = []
    up_to_date_count = 0
    missing_skills: list[dict[str, Any]] = []

    if not errors:
        for row in structured_rows:
            skill_id = str(row.get("skill_id") or "")
            if skill_ids is not None and skill_id not in skill_ids:
                continue
            skill = db.get(SkillDefinition, skill_id) if skill_id else None
            if skill is None or skill.deleted_at is not None:
                missing_skills.append(
                    {
                        "skill_id": skill_id,
                        "skill_name": row.get("skill_name"),
                        "reason": "skill_not_found",
                    }
                )
                continue
            desired = _desired_rule_payload(skill, row)
            changed_fields = _changed_fields(skill, desired)
            if not changed_fields:
                up_to_date_count += 1
                continue
            if limit is None or len(pending_items) < limit:
                pending_items.append(
                    {
                        "skill_id": skill.skill_id,
                        "skill_name": skill.skill_name,
                        "review_status": row.get("review_status"),
                        "review_notes": row.get("review_notes"),
                        "changed_fields": changed_fields,
                        "has_damage_rule": desired["damage_rule_json"] is not None,
                        "has_hit_rule": desired["hit_rule_json"] is not None,
                        "has_effect_operations": desired["effect_operations_json"] is not None,
                    }
                )

    pending_count = _count_pending_items(db, structured_rows, skill_ids) if not errors else 0
    return {
        "source": str(DEFAULT_SKILL_REVIEWS_PATH),
        "total_rows": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "structured_total": len(structured_rows),
        "up_to_date_count": up_to_date_count,
        "pending_count": pending_count,
        "pending_items": pending_items,
        "pending_items_truncated": pending_count > len(pending_items),
        "missing_skills": missing_skills,
        "errors": errors,
        "transaction": "read_only_check",
    }


def _count_pending_items(
    db: Session,
    structured_rows: list[dict[str, Any]],
    skill_ids: set[str] | None,
) -> int:
    count = 0
    for row in structured_rows:
        skill_id = str(row.get("skill_id") or "")
        if skill_ids is not None and skill_id not in skill_ids:
            continue
        skill = db.get(SkillDefinition, skill_id) if skill_id else None
        if skill is None or skill.deleted_at is not None:
            continue
        if _payload_has_difference(skill, _desired_rule_payload(skill, row)):
            count += 1
    return count


def _iter_structured_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("review_status") == "structured" and not row.get("structure_gaps")
    ]


def _desired_rule_payload(skill: SkillDefinition, row: dict[str, Any]) -> dict[str, str | None]:
    return {
        "damage_rule_json": _damage_rule_with_review(skill, row),
        "hit_rule_json": (
            _json_or_none(row["hit_rule"]) if "hit_rule" in row else skill.hit_rule_json
        ),
        "effect_operations_json": (
            _json_or_none(row["effect_operations"])
            if "effect_operations" in row
            else skill.effect_operations_json
        ),
    }


def _payload_has_difference(skill: SkillDefinition, desired: dict[str, str | None]) -> bool:
    return bool(_changed_fields(skill, desired))


def _changed_fields(skill: SkillDefinition, desired: dict[str, str | None]) -> list[str]:
    changed: list[str] = []
    for field, desired_json in desired.items():
        current_json = getattr(skill, field)
        if loads_json(current_json, None) != loads_json(desired_json, None):
            changed.append(field)
    return changed


def _apply_desired_payload(skill: SkillDefinition, desired: dict[str, str | None]) -> None:
    for field, value in desired.items():
        setattr(skill, field, value)
