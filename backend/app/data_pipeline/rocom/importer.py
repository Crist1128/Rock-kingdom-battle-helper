"""
洛克王国 BWIKI 清洗数据导入数据库。

推荐使用方式：

1. 先只清洗并审阅 JSON：
   python -m app.data_pipeline.rocom.cleaner \
     --raw-json ../data/rocom/raw/sprites_raw.json \
     --image-urls-json ../data/rocom/raw/image_urls.json \
     --output-dir ../data/rocom/cleaned

2. 再 dry-run 导入：
   python -m app.data_pipeline.rocom.importer \
     --cleaned-dir ../data/rocom/cleaned

3. 确认后写库：
   python -m app.data_pipeline.rocom.importer \
     --cleaned-dir ../data/rocom/cleaned \
     --commit

默认不提交数据库事务，避免在 MVP 阶段误覆盖人工维护的数据。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data_pipeline.rocom.cleaner import CleanedDataset, clean_from_csv, clean_from_raw_sprites, write_cleaned_dataset
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models.static import ElfDefinition, ElfLearnableSkill, SkillDefinition, TypeEffectivenessRule

ELF_FIELDS = [
    "elf_name",
    "avatar",
    "element_types_json",
    "base_hp_talent",
    "base_physical_attack_talent",
    "base_physical_defense_talent",
    "base_magic_attack_talent",
    "base_magic_defense_talent",
    "base_speed_talent",
    "common_skill_sets_json",
    "common_natures_json",
    "common_individual_talent_patterns_json",
    "forms_json",
    "recognition_templates_json",
    "data_source",
    "data_version",
]

SKILL_FIELDS = [
    "skill_name",
    "alias_names_json",
    "skill_icon",
    "element_type",
    "skill_category",
    "base_power",
    "base_energy_cost",
    "priority_modifier",
    "tags_json",
    "damage_rule_json",
    "hit_rule_json",
    "effect_operations_json",
    "recognition_template_json",
    "data_source",
    "data_version",
]


def read_json(path: Path) -> Any:
    """读取 JSON 文件。"""
    return json.loads(path.read_text(encoding="utf-8"))


def load_cleaned_dataset(cleaned_dir: str | Path) -> CleanedDataset:
    """从 cleaner 输出目录读取 CleanedDataset。"""
    root = Path(cleaned_dir)
    summary_path = root / "import_summary.json"
    summary = read_json(summary_path) if summary_path.exists() else {"stats": {}, "warnings": []}
    return CleanedDataset(
        elves=read_json(root / "elves.json"),
        skills=read_json(root / "skills.json"),
        elf_skills=read_json(root / "elf_learnable_skills.json"),
        type_effectiveness_rules=read_json(root / "type_effectiveness_rules.json"),
        warnings=summary.get("warnings", []),
        stats=summary.get("stats", {}),
    )


def upsert_elf(db: Session, row: dict[str, Any]) -> str:
    """新增或更新 ElfDefinition，返回 created/updated。"""
    elf = db.get(ElfDefinition, row["elf_id"])
    if elf is None:
        elf = ElfDefinition(elf_id=row["elf_id"], **{field: row.get(field) for field in ELF_FIELDS})
        db.add(elf)
        return "created"
    for field in ELF_FIELDS:
        setattr(elf, field, row.get(field))
    elf.deleted_at = None
    return "updated"


def upsert_skill(db: Session, row: dict[str, Any]) -> str:
    """新增或更新 SkillDefinition，返回 created/updated。"""
    skill = db.get(SkillDefinition, row["skill_id"])
    clean_row = {field: row.get(field) for field in SKILL_FIELDS}
    if skill is None:
        skill = SkillDefinition(skill_id=row["skill_id"], **clean_row)
        db.add(skill)
        return "created"
    for field in SKILL_FIELDS:
        setattr(skill, field, clean_row.get(field))
    skill.deleted_at = None
    return "updated"


def upsert_elf_skill_link(db: Session, row: dict[str, Any]) -> str:
    """新增或更新 ElfLearnableSkill。"""
    stmt = select(ElfLearnableSkill).where(
        ElfLearnableSkill.elf_id == row["elf_id"],
        ElfLearnableSkill.skill_id == row["skill_id"],
    )
    link = db.scalars(stmt).first()
    source_parts = [row.get("source") or "biligame_rocom_bwiki"]
    if row.get("learn_level") is not None:
        source_parts.append(f"LV{row['learn_level']}")
    source = ":".join(source_parts)
    if link is None:
        db.add(ElfLearnableSkill(elf_id=row["elf_id"], skill_id=row["skill_id"], source=source))
        return "created"
    link.source = source
    return "updated"


def upsert_type_effectiveness_rule(db: Session, row: dict[str, Any]) -> str:
    """新增或更新 TypeEffectivenessRule。"""
    stmt = select(TypeEffectivenessRule).where(
        TypeEffectivenessRule.attack_element_type == row["attack_element_type"],
        TypeEffectivenessRule.defense_element_type == row["defense_element_type"],
    )
    rule = db.scalars(stmt).first()
    if rule is None:
        db.add(
            TypeEffectivenessRule(
                attack_element_type=row["attack_element_type"],
                defense_element_type=row["defense_element_type"],
                multiplier=float(row["multiplier"]),
                data_version=row.get("data_version"),
            )
        )
        return "created"
    rule.multiplier = float(row["multiplier"])
    rule.data_version = row.get("data_version")
    rule.deleted_at = None
    return "updated"


def import_dataset(db: Session, dataset: CleanedDataset) -> dict[str, Any]:
    """导入清洗后的数据，调用方决定 commit/rollback。"""
    summary: dict[str, Any] = {
        "elves_created": 0,
        "elves_updated": 0,
        "skills_created": 0,
        "skills_updated": 0,
        "elf_skill_links_created": 0,
        "elf_skill_links_updated": 0,
        "type_rules_created": 0,
        "type_rules_updated": 0,
        "warnings": dataset.warnings,
        "source_stats": dataset.stats,
    }

    for row in dataset.elves:
        result = upsert_elf(db, row)
        summary[f"elves_{result}"] += 1

    for row in dataset.skills:
        result = upsert_skill(db, row)
        summary[f"skills_{result}"] += 1

    # 确保主表 INSERT 先落入会话，再插入外键关联。
    db.flush()

    for row in dataset.elf_skills:
        result = upsert_elf_skill_link(db, row)
        summary[f"elf_skill_links_{result}"] += 1

    for row in dataset.type_effectiveness_rules:
        result = upsert_type_effectiveness_rule(db, row)
        summary[f"type_rules_{result}"] += 1

    return summary


def dataset_from_args(args: argparse.Namespace) -> CleanedDataset:
    """根据 CLI 参数读取或生成 CleanedDataset。"""
    if args.cleaned_dir:
        return load_cleaned_dataset(args.cleaned_dir)
    if args.raw_json:
        raw_sprites = read_json(Path(args.raw_json))
        image_url_rows = read_json(Path(args.image_urls_json)) if args.image_urls_json else []
        dataset = clean_from_raw_sprites(
            raw_sprites,
            image_url_rows=image_url_rows,
            lineups_csv=args.lineups_csv,
            data_version=args.data_version,
            image_mode=args.image_mode,
        )
    else:
        dataset = clean_from_csv(
            sprites_csv=args.sprites_csv,
            skills_csv=args.skills_csv,
            urls_csv=args.urls_csv,
            lineups_csv=args.lineups_csv,
            data_version=args.data_version,
            image_mode=args.image_mode,
        )
    if args.write_cleaned_dir:
        write_cleaned_dataset(dataset, args.write_cleaned_dir)
    return dataset


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description="导入洛克王国 BWIKI 清洗数据到后端 SQLite 数据库")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cleaned-dir", help="cleaner 输出目录，包含 elves.json/skills.json 等")
    source.add_argument("--raw-json", help="直接从 sprites_raw.json 清洗并导入，推荐入口")
    source.add_argument("--sprites-csv", help="历史兼容：直接从 sprites.csv 清洗并导入")
    parser.add_argument("--image-urls-json", help="raw-json 模式下的 image_urls.json")
    parser.add_argument("--skills-csv", help="历史兼容：直接清洗模式下的 skills.csv")
    parser.add_argument("--urls-csv", help="历史兼容：直接清洗模式下的 urls.csv")
    parser.add_argument("--lineups-csv", help="直接清洗模式下的 lineups.csv")
    parser.add_argument("--write-cleaned-dir", help="直接清洗模式下同时输出清洗 JSON，便于审阅")
    parser.add_argument("--data-version", help="写入 data_version，如 rocom_bwiki_20260516")
    parser.add_argument(
        "--image-mode",
        choices=["remote", "local"],
        default="remote",
        help="图片引用使用远程 URL 还是本地路径；MVP 推荐 remote",
    )
    parser.add_argument("--skip-init-db", action="store_true", help="跳过 init_db()")
    parser.add_argument("--commit", action="store_true", help="实际提交数据库事务；默认 dry-run 并 rollback")
    return parser


def main() -> None:
    """CLI 入口。"""
    parser = build_parser()
    args = parser.parse_args()

    if not args.skip_init_db:
        init_db()

    dataset = dataset_from_args(args)
    db = SessionLocal()
    try:
        summary = import_dataset(db, dataset)
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
