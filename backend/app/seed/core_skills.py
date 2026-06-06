"""核心默认技能初始化。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.default_skills import DEFAULT_COMMON_SKILL_ID
from app.db.session import SessionLocal
from app.models.static import SkillDefinition
from app.utils.json import dumps_json

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoreSkillSeedResult:
    """核心技能初始化执行结果。"""

    expected_count: int
    created: int
    updated: int
    restored: int

    @property
    def changed(self) -> bool:
        """本次是否实际修改了数据库。"""
        return self.created > 0 or self.updated > 0 or self.restored > 0


def _core_skill_payload() -> dict[str, object]:
    return {
        "skill_name": "聚能",
        "alias_names_json": dumps_json(["通用聚能", "默认聚能"]),
        "skill_icon": None,
        "element_type": "普通",
        "skill_category": "status",
        "base_power": None,
        "base_energy_cost": 0,
        "priority_modifier": 0,
        "tags_json": dumps_json(["default_common_skill", "energy_gain", "status"]),
        "damage_rule_json": dumps_json({"status": "non_damage_resource_gain"}),
        "hit_rule_json": None,
        "effect_operations_json": dumps_json(
            [
                {
                    "operation": "resource_change",
                    "timing": "on_skill_use",
                    "target": "actor_side",
                    "resource_type": "energy",
                    "change_type": "gain",
                    "value_type": "value",
                    "value": 5,
                }
            ]
        ),
        "recognition_template_json": None,
        "data_source": "core_seed",
        "data_version": "core_default",
    }


def ensure_core_skills(db: Session) -> CoreSkillSeedResult:
    """幂等写入/修正战斗核心默认技能。"""
    created = 0
    updated = 0
    restored = 0
    payload = _core_skill_payload()
    skill = db.get(SkillDefinition, DEFAULT_COMMON_SKILL_ID)
    if skill is None:
        db.add(SkillDefinition(skill_id=DEFAULT_COMMON_SKILL_ID, **payload))
        created = 1
    else:
        field_changed = False
        for field, next_value in payload.items():
            if getattr(skill, field) != next_value:
                setattr(skill, field, next_value)
                field_changed = True
        if skill.deleted_at is not None:
            skill.deleted_at = None
            restored = 1
        if field_changed:
            updated = 1
    return CoreSkillSeedResult(
        expected_count=1,
        created=created,
        updated=updated,
        restored=restored,
    )


def ensure_core_skills_with_session() -> CoreSkillSeedResult:
    """创建数据库会话并执行核心默认技能自检。"""
    db = SessionLocal()
    try:
        result = ensure_core_skills(db)
        if result.changed:
            db.commit()
            logger.info(
                "Core skills ensured: expected=%s created=%s updated=%s restored=%s",
                result.expected_count,
                result.created,
                result.updated,
                result.restored,
            )
        else:
            db.rollback()
            logger.info("Core skills already up to date: expected=%s", result.expected_count)
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    """命令行入口：手动补齐核心默认技能。"""
    result = ensure_core_skills_with_session()
    print(
        "Core skills ensured: "
        f"expected={result.expected_count}, "
        f"created={result.created}, "
        f"updated={result.updated}, "
        f"restored={result.restored}"
    )


if __name__ == "__main__":
    main()
