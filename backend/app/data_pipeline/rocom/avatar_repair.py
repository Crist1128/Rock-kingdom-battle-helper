"""从历史 cleaned 数据修复缺失的精灵头像字段。

本工具只更新 `elf_definition.avatar` 为空的记录，避免为了恢复头像而重导
旧版 cleaned 数据，影响新版技能、种族值或技能关系。
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
from app.models.static import ElfDefinition


def read_json(path: Path) -> Any:
    """读取 UTF-8 JSON。"""
    return json.loads(path.read_text(encoding="utf-8"))


def load_avatar_fallbacks(cleaned_dir: str | Path) -> dict[str, str]:
    """从 cleaned/elves.json 加载可复用头像，按 elf_id 和 elf_name 建索引。"""
    rows = read_json(Path(cleaned_dir) / "elves.json")
    fallbacks: dict[str, str] = {}
    for row in rows:
        avatar = str(row.get("avatar") or "").strip()
        if not avatar:
            continue
        elf_id = str(row.get("elf_id") or "").strip()
        elf_name = str(row.get("elf_name") or "").strip()
        if elf_id:
            fallbacks[elf_id] = avatar
        if elf_name:
            fallbacks[elf_name] = avatar
    return fallbacks


def repair_missing_elf_avatars(
    db: Session,
    *,
    fallback_cleaned_dir: str | Path,
) -> dict[str, Any]:
    """修复当前数据库中为空的精灵头像，调用方决定 commit/rollback。"""
    fallbacks = load_avatar_fallbacks(fallback_cleaned_dir)
    rows = list(db.scalars(select(ElfDefinition).where(ElfDefinition.deleted_at.is_(None))))
    updated: list[dict[str, str]] = []
    missing_fallback: list[str] = []

    for elf in rows:
        if elf.avatar and elf.avatar.strip():
            continue
        avatar = fallbacks.get(elf.elf_id) or fallbacks.get(elf.elf_name)
        if not avatar:
            missing_fallback.append(elf.elf_name)
            continue
        elf.avatar = avatar
        updated.append({"elf_id": elf.elf_id, "elf_name": elf.elf_name, "avatar": avatar})

    return {
        "active_elves": len(rows),
        "fallback_avatars": len({value for value in fallbacks.values()}),
        "updated_avatars": len(updated),
        "missing_fallback": len(missing_fallback),
        "updated_examples": updated[:10],
        "missing_examples": missing_fallback[:20],
    }


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description="用历史 cleaned 数据修复缺失的精灵头像")
    parser.add_argument(
        "--fallback-cleaned-dir",
        required=True,
        help="包含 elves.json 的历史 cleaned 目录，用其中非空 avatar 作为 fallback",
    )
    parser.add_argument("--skip-init-db", action="store_true", help="跳过 init_db()")
    parser.add_argument("--commit", action="store_true", help="实际提交；默认 dry-run 并 rollback")
    return parser


def main() -> None:
    """CLI 入口。"""
    args = build_parser().parse_args()
    if not args.skip_init_db:
        init_db()

    db = SessionLocal()
    try:
        summary = repair_missing_elf_avatars(
            db,
            fallback_cleaned_dir=args.fallback_cleaned_dir,
        )
        if args.commit:
            db.commit()
            summary["transaction"] = "committed"
        else:
            db.rollback()
            summary["transaction"] = "rolled_back_dry_run"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
