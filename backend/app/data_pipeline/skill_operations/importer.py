"""技能效果操作规则导入器。

用于把人工整理后的 SkillDefinition.effect_operations_json 写入数据库。
默认 dry-run 并 rollback；只有传入 --commit 才会提交，便于审阅和回滚。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models.static import SkillDefinition
from app.utils.json import dumps_json, loads_json


def read_rows(path: str | Path) -> list[dict[str, Any]]:
    """读取技能操作规则 JSON。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("技能操作规则文件必须是 JSON 数组")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 条规则不是对象")
        rows.append(item)
    return rows


def import_skill_effect_operations(
    db: Session,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """导入技能 effect_operations_json，调用方决定 commit/rollback。"""
    summary: dict[str, Any] = {
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "errors": [],
        "updated_skills": [],
        "skipped_skills": [],
    }
    for index, row in enumerate(rows):
        skill = _find_skill(db, row)
        skill_label = row.get("skill_id") or row.get("skill_name") or f"row_{index}"
        if skill is None:
            summary["skipped"] += 1
            summary["skipped_skills"].append(
                {"skill": skill_label, "reason": "skill_not_found"}
            )
            continue
        operations = row.get("operations")
        if not isinstance(operations, list):
            summary["skipped"] += 1
            error = {"skill": skill_label, "reason": "operations_not_list"}
            summary["errors"].append(error)
            summary["skipped_skills"].append(error)
            continue
        next_json = dumps_json(operations)
        if loads_json(skill.effect_operations_json, None) == operations:
            summary["unchanged"] += 1
            continue
        skill.effect_operations_json = next_json
        summary["updated"] += 1
        summary["updated_skills"].append(
            {
                "skill_id": skill.skill_id,
                "skill_name": skill.skill_name,
                "operation_count": len(operations),
            }
        )
    return summary


def _find_skill(db: Session, row: dict[str, Any]) -> SkillDefinition | None:
    """按 skill_id 或 skill_name 查找技能。"""
    skill_id = row.get("skill_id")
    if isinstance(skill_id, str) and skill_id:
        skill = db.get(SkillDefinition, skill_id)
        if skill is not None and skill.deleted_at is None:
            return skill
    skill_name = row.get("skill_name")
    if isinstance(skill_name, str) and skill_name:
        return db.scalar(
            select(SkillDefinition).where(
                SkillDefinition.skill_name == skill_name,
                SkillDefinition.deleted_at.is_(None),
            )
        )
    return None


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description="导入技能 effect_operations_json")
    parser.add_argument("--input-json", required=True, help="技能操作规则 JSON 文件")
    parser.add_argument("--skip-init-db", action="store_true", help="跳过 init_db()")
    parser.add_argument("--commit", action="store_true", help="实际提交；默认 dry-run rollback")
    return parser


def main() -> None:
    """CLI 入口。"""
    parser = build_parser()
    args = parser.parse_args()

    if not args.skip_init_db:
        init_db()

    rows = read_rows(args.input_json)
    db = SessionLocal()
    try:
        summary = import_skill_effect_operations(db, rows)
        if args.commit:
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
