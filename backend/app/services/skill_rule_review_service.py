"""技能规则审阅服务。

本模块只处理技能规则审阅队列的序列化、人工维护和能力审计辅助解析。
API 层负责 HTTP 状态码转换，服务层负责数据库读写和规则 JSON 解析。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.static import SkillDefinition
from app.schemas.static import (
    SkillDefinitionOut,
    SkillRuleManualUpdate,
    SkillRuleReviewOut,
)
from app.utils.json import dumps_json, loads_json

REVIEW_STATUS_VALUES = {"unreviewed", "structured", "partial", "needs_review", "ambiguous"}


def list_skill_rule_review_items(
    db: Session,
    *,
    q: str | None = None,
    review_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[SkillRuleReviewOut]:
    """列出技能规则审阅队列。"""
    if review_status is not None and review_status not in REVIEW_STATUS_VALUES:
        raise ValueError(f"invalid review_status: {review_status}")

    stmt = select(SkillDefinition).where(SkillDefinition.deleted_at.is_(None))
    if q:
        stmt = stmt.where(SkillDefinition.skill_name.contains(q))
    rows = list(db.scalars(stmt.order_by(SkillDefinition.skill_name)).all())
    items = [skill_review_out(row) for row in rows]
    if review_status is not None:
        items = [item for item in items if item.review_status == review_status]
    return items[offset : offset + limit]


def update_skill_rule_review(
    db: Session,
    *,
    skill_id: str,
    payload: SkillRuleManualUpdate,
) -> SkillRuleReviewOut:
    """手动写入明确技能规则，或仅标记审阅状态。"""
    if payload.review_status not in REVIEW_STATUS_VALUES:
        raise ValueError(f"invalid review_status: {payload.review_status}")
    skill = db.get(SkillDefinition, skill_id)
    if skill is None or skill.deleted_at is not None:
        raise LookupError("Skill not found")

    fields = payload.model_fields_set
    if "damage_rule" in fields:
        skill.damage_rule_json = _json_or_none(payload.damage_rule)
    if "hit_rule" in fields:
        skill.hit_rule_json = _json_or_none(payload.hit_rule)
    if "effect_operations" in fields:
        skill.effect_operations_json = _json_or_none(payload.effect_operations)

    _write_manual_review(skill, payload.review_status, payload.review_notes)
    db.commit()
    db.refresh(skill)
    return skill_review_out(skill)


def skill_review_out(skill: SkillDefinition) -> SkillRuleReviewOut:
    """把技能定义转换为前端规则审阅行。"""
    damage_rule = loads_json(skill.damage_rule_json, None)
    hit_rule = loads_json(skill.hit_rule_json, None)
    effect_operations_json = loads_json(skill.effect_operations_json, None)
    review = damage_rule.get("manual_review", {}) if isinstance(damage_rule, dict) else {}
    has_damage_rule = _has_meaningful_damage_rule(damage_rule)
    has_hit_rule = isinstance(hit_rule, dict) and bool(hit_rule)
    has_effect_operations = (
        isinstance(effect_operations_json, list) and bool(effect_operations_json)
    )
    status_value = review.get("status") if isinstance(review, dict) else None
    review_status = (
        str(status_value)
        if isinstance(status_value, str) and status_value in REVIEW_STATUS_VALUES
        else "structured"
        if has_damage_rule or has_effect_operations
        else "partial"
        if has_hit_rule
        else "unreviewed"
    )
    review_notes = (
        str(review.get("notes"))
        if isinstance(review, dict) and review.get("notes") is not None
        else None
    )
    data = SkillDefinitionOut.model_validate(skill).model_dump()
    return SkillRuleReviewOut(
        **data,
        review_status=review_status,
        review_notes=review_notes,
        has_damage_rule=has_damage_rule,
        has_hit_rule=has_hit_rule,
        has_effect_operations=has_effect_operations,
        rule_source=(
            "manual"
            if isinstance(review, dict) and review
            else "structured_json"
            if has_damage_rule or has_effect_operations
            else "hit_rule_only"
            if has_hit_rule
            else "none"
        ),
    )


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return dumps_json(value)


def _write_manual_review(
    skill: SkillDefinition,
    review_status: str,
    review_notes: str | None,
) -> None:
    rule = loads_json(skill.damage_rule_json, None)
    if not isinstance(rule, dict):
        rule = {}
    rule["manual_review"] = {
        "status": review_status,
        "notes": review_notes,
        "source": "manual_skill_rule_editor",
    }
    skill.damage_rule_json = dumps_json(rule)


def _has_meaningful_damage_rule(rule: Any) -> bool:
    if not isinstance(rule, dict) or not rule:
        return False
    return any(key != "manual_review" for key in rule)
