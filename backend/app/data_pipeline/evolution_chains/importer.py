"""精灵进化链种子数据导入器。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models.static import ElfDefinition, ElfEvolutionChain, ElfEvolutionStage
from app.utils.json import dumps_json

DEFAULT_SOURCE = "project_seed_evolution_chains"
DEFAULT_SEED_PATH = BACKEND_DIR / "app" / "seed" / "elf_evolution_chains.json"


def read_evolution_chain_rows(path: str | Path = DEFAULT_SEED_PATH) -> list[dict[str, Any]]:
    """读取进化链 seed JSON。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Evolution chain seed must be a list")
    return [row for row in data if isinstance(row, dict)]


def import_evolution_chains(
    db: Session,
    rows: list[dict[str, Any]],
    *,
    source: str = DEFAULT_SOURCE,
    refresh_source: bool = True,
) -> dict[str, Any]:
    """导入进化链。

    调用方负责事务提交或回滚；数据更新入口默认先 dry-run，再由用户确认 commit。
    """
    summary: dict[str, Any] = {
        "chains_created": 0,
        "chains_updated": 0,
        "chains_refreshed": 0,
        "stages_created": 0,
        "stages_skipped_missing_elf": 0,
        "stages_skipped_duplicate_chain_elf": 0,
        "refresh_source": refresh_source,
        "source": source,
    }

    if refresh_source:
        chain_ids = set(
            db.scalars(select(ElfEvolutionChain.chain_id).where(ElfEvolutionChain.source == source))
        )
        if chain_ids:
            db.execute(delete(ElfEvolutionStage).where(ElfEvolutionStage.chain_id.in_(chain_ids)))
            db.execute(delete(ElfEvolutionChain).where(ElfEvolutionChain.chain_id.in_(chain_ids)))
        summary["chains_refreshed"] = len(chain_ids)

    db.flush()
    active_elf_ids = set(
        db.scalars(select(ElfDefinition.elf_id).where(ElfDefinition.deleted_at.is_(None)))
    )

    for row in rows:
        chain_id = str(row.get("chain_id") or "").strip()
        chain_key = str(row.get("chain_key") or chain_id).strip()
        if not chain_id or not chain_key:
            continue
        chain = db.get(ElfEvolutionChain, chain_id)
        chain_payload = {
            "chain_key": chain_key,
            "chain_name": row.get("chain_name"),
            "source": row.get("source") or source,
            "data_version": row.get("data_version"),
            "notes": row.get("notes"),
        }
        if chain is None:
            db.add(ElfEvolutionChain(chain_id=chain_id, **chain_payload))
            summary["chains_created"] += 1
        else:
            for field, value in chain_payload.items():
                setattr(chain, field, value)
            chain.deleted_at = None
            summary["chains_updated"] += 1

        seen_stage_elf_ids: set[str] = set()
        stages = row.get("stages") if isinstance(row.get("stages"), list) else []
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            elf_id = str(stage.get("elf_id") or "").strip()
            if not elf_id or elf_id not in active_elf_ids:
                summary["stages_skipped_missing_elf"] += 1
                continue
            if elf_id in seen_stage_elf_ids:
                summary["stages_skipped_duplicate_chain_elf"] += 1
                continue
            seen_stage_elf_ids.add(elf_id)
            stage_index = int(stage.get("stage_index") or stage.get("stage") or 0)
            stage_row = ElfEvolutionStage(
                chain_id=chain_id,
                elf_id=elf_id,
                stage_index=stage_index,
                stage_name=str(stage.get("stage_name") or stage.get("name") or ""),
                form_name=stage.get("form_name"),
                evolves_from_elf_id=stage.get("evolves_from_elf_id"),
                condition_json=_json_or_none(stage.get("condition")),
                source_stage_json=dumps_json(stage),
                data_version=row.get("data_version"),
            )
            db.add(stage_row)
            summary["stages_created"] += 1

    return summary


def import_evolution_chain_seed(
    db: Session,
    *,
    path: str | Path = DEFAULT_SEED_PATH,
    source: str = DEFAULT_SOURCE,
    refresh_source: bool = True,
) -> dict[str, Any]:
    """从默认 seed 文件导入进化链。"""
    return import_evolution_chains(
        db,
        read_evolution_chain_rows(path),
        source=source,
        refresh_source=refresh_source,
    )


def _json_or_none(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return dumps_json(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import elf evolution chain seed data.")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED_PATH)
    parser.add_argument("--skip-init-db", action="store_true")
    parser.add_argument("--commit", action="store_true", help="实际提交；默认 dry-run rollback")
    parser.add_argument("--no-refresh-source", action="store_true", help="不清理同 source 旧链")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.skip_init_db:
        init_db()
    db = SessionLocal()
    try:
        summary = import_evolution_chain_seed(
            db,
            path=args.seed,
            refresh_source=not args.no_refresh_source,
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
