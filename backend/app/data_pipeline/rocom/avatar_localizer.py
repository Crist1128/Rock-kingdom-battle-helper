"""把 cleaned 中的本地头像路径同步为前端可访问的后端 URL。

本工具只更新 `elf_definition.avatar` 字段，不导入其它 rocom 静态数据，适合在已经使用
`scraper --with-images` 下载图片、并用 `cleaner --image-mode local` 生成 cleaned JSON 后运行。
默认 dry-run 并回滚；确认摘要无误后再追加 `--commit`。
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

ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


def read_json(path: Path) -> Any:
    """读取 UTF-8 JSON 文件。"""
    return json.loads(path.read_text(encoding="utf-8"))


def load_cleaned_elves(cleaned_dir: str | Path) -> list[dict[str, Any]]:
    """读取 cleaned/elves.json。"""
    rows = read_json(Path(cleaned_dir) / "elves.json")
    if not isinstance(rows, list):
        raise ValueError("cleaned elves.json must be a JSON array")
    return [row for row in rows if isinstance(row, dict)]


def _is_remote_avatar(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "//"))


def _resolve_local_avatar_file(image_base_dir: Path, avatar: str) -> Path | None:
    """解析 cleaned 头像相对路径；非法路径返回 None。"""
    if "\\" in avatar:
        avatar = avatar.replace("\\", "/")
    requested = Path(avatar)
    if requested.is_absolute() or any(part in {"", ".", ".."} for part in requested.parts):
        return None
    if requested.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
        return None
    root = image_base_dir.resolve()
    candidate = (root / requested).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _asset_url(url_prefix: str, avatar: str) -> str:
    """把本地相对头像路径转换为后端静态资源 URL。"""
    normalized_avatar = avatar.replace("\\", "/").lstrip("/")
    return f"{url_prefix.rstrip('/')}/{normalized_avatar}"


def localize_elf_avatars(
    db: Session,
    *,
    cleaned_dir: str | Path,
    image_base_dir: str | Path,
    url_prefix: str,
) -> dict[str, Any]:
    """按 cleaned 本地头像路径更新现有精灵头像 URL，事务由调用方决定。"""
    rows = load_cleaned_elves(cleaned_dir)
    image_root = Path(image_base_dir)
    summary: dict[str, Any] = {
        "total_rows": len(rows),
        "updated": 0,
        "unchanged": 0,
        "skipped_missing_elf": 0,
        "skipped_empty_avatar": 0,
        "skipped_remote_avatar": 0,
        "skipped_invalid_path": 0,
        "skipped_missing_file": 0,
        "updated_examples": [],
        "errors": [],
    }

    for index, row in enumerate(rows):
        elf_id = str(row.get("elf_id") or "").strip()
        elf_name = str(row.get("elf_name") or "").strip()
        avatar = str(row.get("avatar") or "").strip()

        if not elf_id:
            summary["errors"].append({"row_index": index, "reason": "missing_elf_id"})
            continue
        if not avatar:
            summary["skipped_empty_avatar"] += 1
            continue
        if _is_remote_avatar(avatar):
            summary["skipped_remote_avatar"] += 1
            continue

        avatar_file = _resolve_local_avatar_file(image_root, avatar)
        if avatar_file is None:
            summary["skipped_invalid_path"] += 1
            continue
        if not avatar_file.is_file():
            summary["skipped_missing_file"] += 1
            continue

        elf = db.scalars(
            select(ElfDefinition).where(
                ElfDefinition.elf_id == elf_id,
                ElfDefinition.deleted_at.is_(None),
            )
        ).first()
        if elf is None:
            summary["skipped_missing_elf"] += 1
            continue

        new_avatar = _asset_url(url_prefix, avatar)
        if elf.avatar == new_avatar:
            summary["unchanged"] += 1
            continue

        old_avatar = elf.avatar
        elf.avatar = new_avatar
        summary["updated"] += 1
        if len(summary["updated_examples"]) < 10:
            summary["updated_examples"].append(
                {
                    "elf_id": elf_id,
                    "elf_name": elf_name or elf.elf_name,
                    "old_avatar": old_avatar,
                    "new_avatar": new_avatar,
                }
            )

    return summary


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description="把 rocom 本地精灵头像同步为后端可访问 URL")
    parser.add_argument("--cleaned-dir", required=True, help="包含 elves.json 的 cleaned 目录")
    parser.add_argument(
        "--image-base-dir",
        required=True,
        help="cleaned 头像相对路径的文件根目录，例如 ../data/rocom/raw_with_images",
    )
    parser.add_argument(
        "--url-prefix",
        required=True,
        help="前端访问图片时使用的 URL 前缀，例如 /api/v1/assets/rocom/raw_with_images",
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
        summary = localize_elf_avatars(
            db,
            cleaned_dir=args.cleaned_dir,
            image_base_dir=args.image_base_dir,
            url_prefix=args.url_prefix,
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
