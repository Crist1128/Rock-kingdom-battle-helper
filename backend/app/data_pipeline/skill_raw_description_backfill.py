"""从 cleaned 技能数据回填技能中文原文描述。

该脚本只写入 `skill_definition.raw_description`，不会触碰伤害规则、
命中规则或结构化效果操作，适合在重爬前后单独修复前端展示用原文。
默认 dry-run；显式传入 `--commit` 才会提交数据库事务。
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

DEFAULT_SKILLS_JSON = (
    Path(__file__).resolve().parents[3] / "data" / "rocom" / "cleaned" / "skills.json"
)


def read_cleaned_skills(path: str | Path = DEFAULT_SKILLS_JSON) -> list[dict[str, Any]]:
    """读取 rocom cleaner 输出的 skills.json。"""
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"{path} 必须是 JSON 数组")
    return [item for item in data if isinstance(item, dict)]


def backfill_skill_raw_descriptions(
    db: Session,
    rows: list[dict[str, Any]],
    *,
    only_missing: bool = False,
) -> dict[str, Any]:
    """按 skill_id 优先、skill_name 兜底回填 raw_description。"""
    summary: dict[str, Any] = {
        "total_rows": len(rows),
        "rows_with_raw_description": 0,
        "skills_updated": 0,
        "skills_unchanged": 0,
        "skills_missing": 0,
        "skills_skipped_empty": 0,
        "skill_name_fallbacks": [],
        "skill_name_conflicts": [],
        "missing_skill_ids": [],
        "updated_examples": [],
        "only_missing": only_missing,
    }
    source_counts: Counter[str] = Counter()

    for row in rows:
        skill_id = str(row.get("skill_id") or "")
        skill_name = str(row.get("skill_name") or "")
        raw_description = _clean_text(row.get("raw_description"))
        if not raw_description:
            summary["skills_skipped_empty"] += 1
            continue
        summary["rows_with_raw_description"] += 1

        skill = db.get(SkillDefinition, skill_id) if skill_id else None
        if skill is None or skill.deleted_at is not None:
            fallback, conflict_count = _find_active_skill_by_name(db, skill_name)
            if fallback is not None:
                skill = fallback
                summary["skill_name_fallbacks"].append(
                    {
                        "source_skill_id": skill_id or None,
                        "skill_name": skill_name,
                        "matched_skill_id": skill.skill_id,
                    }
                )
            elif conflict_count > 1:
                summary["skill_name_conflicts"].append(
                    {
                        "source_skill_id": skill_id or None,
                        "skill_name": skill_name,
                        "match_count": conflict_count,
                    }
                )

        if skill is None or skill.deleted_at is not None:
            summary["skills_missing"] += 1
            summary["missing_skill_ids"].append(skill_id or skill_name)
            continue

        current = _clean_text(skill.raw_description)
        if current == raw_description or (only_missing and current):
            summary["skills_unchanged"] += 1
            continue

        skill.raw_description = raw_description
        summary["skills_updated"] += 1
        source_counts[str(row.get("data_source") or "unknown")] += 1
        if len(summary["updated_examples"]) < 10:
            summary["updated_examples"].append(
                {
                    "skill_id": skill.skill_id,
                    "skill_name": skill.skill_name,
                    "raw_description": raw_description,
                }
            )

    db.flush()
    summary["updated_source_counts"] = dict(sorted(source_counts.items()))
    return summary


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _find_active_skill_by_name(
    db: Session,
    skill_name: str,
) -> tuple[SkillDefinition | None, int]:
    if not skill_name:
        return None, 0
    matches = list(
        db.scalars(
            select(SkillDefinition).where(
                SkillDefinition.skill_name == skill_name,
                SkillDefinition.deleted_at.is_(None),
            )
        ).all()
    )
    return (matches[0], len(matches)) if len(matches) == 1 else (None, len(matches))


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description="回填 skill_definition.raw_description")
    parser.add_argument(
        "--skills-json",
        default=str(DEFAULT_SKILLS_JSON),
        help="rocom cleaner 输出的 skills.json",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="只填充当前为空的 raw_description；默认会按 cleaned 原文更新差异",
    )
    parser.add_argument("--skip-init-db", action="store_true", help="跳过 init_db()")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="实际提交数据库事务；默认 dry-run 并 rollback",
    )
    return parser


def main() -> None:
    """CLI 入口。"""
    parser = build_parser()
    args = parser.parse_args()
    if not args.skip_init_db:
        init_db()

    rows = read_cleaned_skills(args.skills_json)
    db = SessionLocal()
    try:
        summary = backfill_skill_raw_descriptions(
            db,
            rows,
            only_missing=args.only_missing,
        )
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
