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

from app.data_pipeline.effects.importer import (
    EFFECT_DEFINITION_FIELDS,
    JSON_FIELDS,
    import_effect_definitions,
    read_effect_rows,
    validate_effect_rows,
)
from app.data_pipeline.effects.importer import (
    _normalize_field as _normalize_effect_field,
)
from app.data_pipeline.skill_rule_reviews.importer import (
    _damage_rule_with_review,
    _json_or_none,
    read_review_rows,
    validate_review_rows,
)
from app.models.static import EffectDefinition, SkillDefinition
from app.utils.json import loads_json

DEFAULT_SEED_DIR = Path(__file__).resolve().parents[1] / "seed"
DEFAULT_SKILL_REVIEWS_PATH = DEFAULT_SEED_DIR / "manual_skill_rule_reviews_all_20260612.json"
DEFAULT_EFFECT_DEFINITION_PATHS = (
    DEFAULT_SEED_DIR / "manual_skill_effect_definitions_all_20260612.json",
    DEFAULT_SEED_DIR / "effect_definitions_p0.json",
)


def check_structured_skill_rule_sync(
    db: Session,
    *,
    reviews_json: str | Path | None = None,
    effect_json_paths: list[str | Path] | None = None,
    limit: int | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """检查 structured 技能规则与状态定义 seed 是否一致，不修改数据库。"""
    rows = _read_rows(reviews_json)
    effect_rows_by_path = _read_effect_rows_by_path(effect_json_paths)
    return _build_sync_plan(db, rows, effect_rows_by_path, limit=limit, q=q)


def check_effect_definition_seed_sync(
    db: Session,
    *,
    effect_json_paths: list[str | Path] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """只检查项目状态定义 seed 与数据库是否一致。"""
    return _build_effect_sync_plan(
        db,
        _read_effect_rows_by_path(effect_json_paths),
        limit=limit,
    )


def sync_structured_skill_rules(
    db: Session,
    *,
    skill_ids: list[str] | None = None,
    commit: bool = False,
    reviews_json: str | Path | None = None,
    effect_json_paths: list[str | Path] | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """把选中的 structured 技能规则与状态定义写入数据库；默认 dry-run。"""
    rows = _read_rows(reviews_json)
    effect_rows_by_path = _read_effect_rows_by_path(effect_json_paths)
    skill_id_set = {str(item) for item in skill_ids or [] if str(item)}
    plan = _build_sync_plan(db, rows, effect_rows_by_path, skill_ids=skill_id_set or None, q=q)
    if plan.get("errors"):
        db.rollback()
        plan["applied_skill_ids"] = []
        plan["applied_effect_ids"] = []
        plan["applied_count"] = 0
        plan["applied_skill_count"] = 0
        plan["applied_effect_count"] = 0
        plan["transaction"] = "rolled_back_validation_error"
        return plan
    applied_skill_ids: set[str] = set()
    effect_plan = _build_effect_sync_plan(db, effect_rows_by_path, limit=None)
    applied_effect_ids = [
        str(item.get("effect_id"))
        for item in effect_plan.get("pending_items", [])
        if item.get("effect_id")
    ]
    for _path, effect_rows in _unique_effect_rows_by_path(effect_rows_by_path):
        import_effect_definitions(db, effect_rows)
    for row in _iter_structured_rows(rows):
        skill_id = str(row.get("skill_id") or "")
        if skill_id_set and skill_id not in skill_id_set:
            continue
        if q is not None and not _row_matches_query(row, q):
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
        refreshed_plan = _build_sync_plan(
            db,
            rows,
            effect_rows_by_path,
            skill_ids=skill_id_set or None,
            q=q,
        )
        plan.update(
            {
                key: value
                for key, value in refreshed_plan.items()
                if key
                not in {
                    "applied_skill_ids",
                    "applied_effect_ids",
                    "applied_count",
                    "applied_skill_count",
                    "applied_effect_count",
                    "transaction",
                }
            }
        )
    else:
        db.rollback()
        transaction = "rolled_back_dry_run"
    plan["applied_skill_ids"] = sorted(applied_skill_ids)
    plan["applied_effect_ids"] = sorted(applied_effect_ids)
    plan["applied_count"] = len(applied_skill_ids) + len(applied_effect_ids)
    plan["applied_skill_count"] = len(applied_skill_ids)
    plan["applied_effect_count"] = len(applied_effect_ids)
    plan["transaction"] = transaction
    return plan


def _read_rows(reviews_json: str | Path | None) -> list[dict[str, Any]]:
    path = Path(reviews_json) if reviews_json is not None else DEFAULT_SKILL_REVIEWS_PATH
    return read_review_rows(path)


def _read_effect_rows_by_path(
    effect_json_paths: list[str | Path] | None,
) -> list[tuple[Path, list[dict[str, Any]]]]:
    paths = (
        [Path(item) for item in effect_json_paths]
        if effect_json_paths is not None
        else list(DEFAULT_EFFECT_DEFINITION_PATHS)
    )
    return [(path, read_effect_rows(path)) for path in paths]


def _unique_effect_rows_by_path(
    effect_rows_by_path: list[tuple[Path, list[dict[str, Any]]]],
) -> list[tuple[Path, list[dict[str, Any]]]]:
    """按 seed 优先级去重状态定义；同 effect_id 只导入第一份。"""
    seen_effect_ids: set[str] = set()
    unique_groups: list[tuple[Path, list[dict[str, Any]]]] = []
    for path, rows in effect_rows_by_path:
        unique_rows: list[dict[str, Any]] = []
        for row in rows:
            effect_id = str(row.get("effect_id") or "")
            if not effect_id or effect_id in seen_effect_ids:
                continue
            seen_effect_ids.add(effect_id)
            unique_rows.append(row)
        if unique_rows:
            unique_groups.append((path, unique_rows))
    return unique_groups


def _build_sync_plan(
    db: Session,
    rows: list[dict[str, Any]],
    effect_rows_by_path: list[tuple[Path, list[dict[str, Any]]]],
    *,
    skill_ids: set[str] | None = None,
    limit: int | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    effect_plan = _build_effect_sync_plan(db, effect_rows_by_path, limit=limit)
    errors = [*validate_review_rows(rows), *effect_plan.get("errors", [])]
    status_counts: Counter[str] = Counter(str(row.get("review_status")) for row in rows)
    structured_rows = [
        row
        for row in _iter_structured_rows(rows)
        if q is None or _row_matches_query(row, q)
    ]
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

    skill_pending_count = _count_pending_items(db, structured_rows, skill_ids) if not errors else 0
    effect_pending_count = int(effect_plan.get("pending_count") or 0) if not errors else 0
    pending_count = skill_pending_count + effect_pending_count
    return {
        "source": str(DEFAULT_SKILL_REVIEWS_PATH),
        "query": _normalize_query(q),
        "total_rows": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "structured_total": len(structured_rows),
        "up_to_date_count": up_to_date_count,
        "skill_up_to_date_count": up_to_date_count,
        "effect_up_to_date_count": effect_plan.get("up_to_date_count", 0),
        "pending_count": pending_count,
        "pending_skill_count": skill_pending_count,
        "pending_effect_count": effect_pending_count,
        "pending_items": pending_items,
        "pending_items_truncated": skill_pending_count > len(pending_items),
        "effect_definition_sync": effect_plan,
        "effect_pending_items": effect_plan.get("pending_items", []),
        "missing_skills": missing_skills,
        "errors": errors,
        "transaction": "read_only_check",
    }



def _build_effect_sync_plan(
    db: Session,
    effect_rows_by_path: list[tuple[Path, list[dict[str, Any]]]],
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """构造状态定义同步计划，不修改数据库。"""
    errors: list[str] = []
    pending_items: list[dict[str, Any]] = []
    up_to_date_count = 0
    total_rows = 0
    seen_effect_ids: set[str] = set()
    sources: list[str] = []

    for path, rows in effect_rows_by_path:
        sources.append(str(path))
        total_rows += len(rows)
        errors.extend(f"{path.name}: {error}" for error in validate_effect_rows(rows))
        if errors:
            continue
        for row in rows:
            effect_id = str(row.get("effect_id") or "")
            if not effect_id or effect_id in seen_effect_ids:
                continue
            seen_effect_ids.add(effect_id)
            current = db.get(EffectDefinition, effect_id)
            desired = _desired_effect_payload(row)
            changed_fields = _changed_effect_fields(current, desired)
            if not changed_fields:
                up_to_date_count += 1
                continue
            if limit is None or len(pending_items) < limit:
                pending_items.append(
                    {
                        "effect_id": effect_id,
                        "effect_name": row.get("effect_name"),
                        "source_file": path.name,
                        "changed_fields": changed_fields,
                        "reason": "effect_not_found"
                        if current is None or current.deleted_at is not None
                        else "effect_out_of_date",
                    }
                )

    pending_count = len(seen_effect_ids) - up_to_date_count if not errors else 0
    return {
        "sources": sources,
        "total_rows": total_rows,
        "up_to_date_count": up_to_date_count,
        "pending_count": pending_count,
        "pending_items": pending_items,
        "pending_items_truncated": pending_count > len(pending_items),
        "errors": errors,
    }


def _desired_effect_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        field: _normalize_effect_field(field, row.get(field))
        for field in EFFECT_DEFINITION_FIELDS
    }


def _changed_effect_fields(
    current: EffectDefinition | None,
    desired: dict[str, Any],
) -> list[str]:
    if current is None or current.deleted_at is not None:
        return ["effect_definition"]
    changed: list[str] = []
    for field, desired_value in desired.items():
        current_value = getattr(current, field)
        if field in JSON_FIELDS:
            if loads_json(current_value, None) != loads_json(desired_value, None):
                changed.append(field)
        elif current_value != desired_value:
            changed.append(field)
    return changed

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


def _normalize_query(q: str | None) -> str | None:
    if q is None:
        return None
    normalized = q.strip().lower()
    return normalized or None


def _row_matches_query(row: dict[str, Any], q: str | None) -> bool:
    """按技能 ID 或名称筛选同步检查结果，避免被默认 limit 截断看不到目标技能。"""
    normalized = _normalize_query(q)
    if normalized is None:
        return True
    searchable_values = [
        row.get("skill_id"),
        row.get("skill_name"),
        row.get("review_notes"),
    ]
    return any(
        normalized in str(value).lower()
        for value in searchable_values
        if value is not None
    )


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
