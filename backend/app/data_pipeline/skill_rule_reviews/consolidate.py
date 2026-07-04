"""整合技能人工审阅种子文件并校验数据库覆盖。

本脚本只处理 ``backend/app/seed`` 下的人工技能规则种子：

- ``manual_skill_effect_definitions*.json``：人工补充状态定义；
- ``manual_skill_rule_reviews*.json``：人工技能规则审阅。

设计目标：

1. 把历史分批文件合并为稳定的总文件，后续导入优先使用总文件；
2. 使用 ``ensure_ascii=False`` 重写 JSON，避免中文被保存成 ``\\uXXXX``；
3. 对已知的历史问号占位损坏文本做显式修复；
4. 与当前 SQLite 数据库比对，确认 active rocom 技能和带拓展分支的技能都有覆盖。

默认只生成总文件和报告；只有传入 ``--rewrite-sources`` 才会重写历史分批文件。
历史分批 JSON 已从当前工作树移除以缩减仓库体积；如需重新整合，请先从
Git 历史恢复源文件，或在 ``app/seed`` / ``app/seed/archive/manual_reviews_20260612``
放入新的分批源文件。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import OrderedDict
from pathlib import Path
from typing import Any

DEFAULT_EFFECTS_OUT = "manual_skill_effect_definitions_all_20260612.json"
DEFAULT_REVIEWS_OUT = "manual_skill_rule_reviews_all_20260612.json"
DEFAULT_REPORT_OUT = "manual_skill_rules_consolidation_report_20260612.json"
ARCHIVE_SOURCE_SUBDIR = Path("archive/manual_reviews_20260612")

MOJIBAKE_MARKERS = (
    "?" * 4,
    "?" * 2,
    "\u951b",
    "\u93b4",
    "\u9473",
    "\u6fde",
    "\u93c8",
    "\ufffd",
)


def read_json_rows(path: Path) -> list[dict[str, Any]]:
    """读取顶层为数组的 JSON 文件。"""
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{path} 顶层必须是数组")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path} 每一项都必须是对象")
    return rows


def write_json(path: Path, rows: list[dict[str, Any]] | dict[str, Any]) -> None:
    """以 UTF-8、非 ASCII 转义格式写出 JSON。"""
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def source_files(seed_dir: Path, prefix: str) -> list[Path]:
    """查找可整合的历史分批源文件。

    会跳过已经整合好的 ``*_all_20260612.json`` 和整合报告，避免把总文件再次当
    源文件读入。当前仓库默认只保留总文件；该函数主要用于后续新增分批源文件时
    重新生成总文件。
    """
    search_dirs = [seed_dir, seed_dir / ARCHIVE_SOURCE_SUBDIR]
    files: list[Path] = []
    for base_dir in search_dirs:
        if not base_dir.exists():
            continue
        files.extend(
            path
            for path in sorted(base_dir.glob(f"{prefix}*.json"))
            if "_all_" not in path.name and "consolidation_report" not in path.name
        )
    return files


def repair_known_corruption(rows: list[dict[str, Any]], kind: str) -> list[str]:
    """修复已可从上下文确认的历史损坏文本，返回修复说明。"""
    changes: list[str] = []
    if kind == "effect":
        for row in rows:
            effect_id = row.get("effect_id")
            if effect_id == "effect_charge_ready":
                if row.get("effect_name") != "蓄力就绪":
                    changes.append("effect_charge_ready.effect_name: 历史损坏文本 -> 蓄力就绪")
                row["effect_name"] = "蓄力就绪"
                row["recognition_alias_json"] = ["蓄力就绪", "蓄力"]
            elif effect_id == "effect_next_charge_free":
                if row.get("effect_name") != "下次技能无需蓄力":
                    changes.append(
                        "effect_next_charge_free.effect_name: 历史损坏文本 -> 下次技能无需蓄力"
                    )
                row["effect_name"] = "下次技能无需蓄力"
                row["recognition_alias_json"] = ["下次技能无需蓄力", "免蓄力"]
    elif kind == "review":
        for row in rows:
            skill_id = row.get("skill_id")
            if skill_id == "rocom_skill_cb7f7c0e2b":
                for hook in row.get("future_hooks") or []:
                    if (
                        isinstance(hook, dict)
                        and hook.get("hook_type") == "auto_skill_use_after_element_count"
                    ):
                        if hook.get("element_type") != "wing":
                            changes.append("疾风涡轮.future_hooks.element_type: ? -> wing")
                        hook["element_type"] = "wing"
                        hook["element_name"] = "翼"
            elif skill_id == "rocom_skill_1377598619":
                hit_rule = row.get("hit_rule")
                if isinstance(hit_rule, dict):
                    dynamic_hit_rule = hit_rule.get("dynamic_hit_rule")
                    if isinstance(dynamic_hit_rule, dict):
                        if dynamic_hit_rule.get("skill_name") != "虫鸣":
                            changes.append("虫鸣.hit_rule.dynamic_hit_rule.skill_name: ?? -> 虫鸣")
                        dynamic_hit_rule["skill_name"] = "虫鸣"
                for hook in row.get("future_hooks") or []:
                    if (
                        isinstance(hook, dict)
                        and hook.get("hook_type") == "hit_count_from_team_skill_count"
                    ):
                        if hook.get("skill_name") != "虫鸣":
                            changes.append("虫鸣.future_hooks.skill_name: ?? -> 虫鸣")
                        hook["skill_name"] = "虫鸣"
    return changes


def consolidate_rows(
    files: list[Path],
    key_field: str,
    kind: str,
    rewrite_sources: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按文件顺序合并行；重复 key 后者覆盖前者，但保留首次出现位置。"""
    merged: OrderedDict[str, dict[str, Any]] = OrderedDict()
    source_by_key: dict[str, str] = {}
    duplicates: list[dict[str, str]] = []
    repair_changes: list[str] = []
    source_counts: dict[str, int] = {}

    for path in files:
        rows = read_json_rows(path)
        repair_changes.extend(
            f"{path.name}: {item}" for item in repair_known_corruption(rows, kind)
        )
        source_counts[path.name] = len(rows)
        if rewrite_sources:
            write_json(path, rows)
        for index, row in enumerate(rows):
            key = row.get(key_field)
            if not key:
                raise ValueError(f"{path} row[{index}] 缺少 {key_field}")
            key_text = str(key)
            if key_text in merged:
                duplicates.append(
                    {
                        key_field: key_text,
                        "previous_source": source_by_key[key_text],
                        "override_source": path.name,
                    }
                )
            merged[key_text] = row
            source_by_key[key_text] = path.name

    summary = {
        "source_files": [path.name for path in files],
        "source_counts": source_counts,
        "unique_count": len(merged),
        "duplicate_overrides": duplicates,
        "repair_changes": repair_changes,
    }
    return list(merged.values()), summary


def find_suspicious_strings(data: Any) -> list[dict[str, str]]:
    """查找明显损坏文本和仍保留的 Unicode 转义文本。"""
    findings: list[dict[str, str]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
        elif isinstance(value, str):
            if any(marker in value for marker in MOJIBAKE_MARKERS):
                findings.append({"path": path, "value": value, "kind": "mojibake_marker"})
            if re.search(r"\\u[0-9a-fA-F]{4}", value):
                findings.append({"path": path, "value": value, "kind": "literal_unicode_escape"})

    walk(data, "")
    return findings


def load_db_skill_rows(db_path: Path) -> dict[str, dict[str, Any]]:
    """读取数据库中的 active rocom 技能。"""
    if not db_path.exists():
        return {}
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            select skill_id, skill_name, damage_rule_json, hit_rule_json, effect_operations_json
            from skill_definition
            where skill_id like 'rocom_skill_%'
              and deleted_at is null
            order by skill_name, skill_id
            """
        ).fetchall()
    finally:
        con.close()
    return {str(row["skill_id"]): dict(row) for row in rows}


def has_extension_branch_from_review(row: dict[str, Any]) -> bool:
    """判断审阅行是否包含待执行/已执行的拓展分支。"""
    if row.get("future_hooks") or row.get("structure_gaps"):
        return True
    damage_rule = row.get("damage_rule")
    if isinstance(damage_rule, dict):
        return any(
            key in damage_rule
            for key in (
                "response_rule",
                "conditional_branches",
                "dynamic_power_rule",
                "dynamic_damage_rule",
            )
        )
    hit_rule = row.get("hit_rule")
    if isinstance(hit_rule, dict):
        return "dynamic_hit_rule" in hit_rule
    effect_operations = row.get("effect_operations")
    if isinstance(effect_operations, list):
        return any(
            isinstance(operation, dict)
            and operation.get("operation_type") in {"conditional_branch", "dynamic_apply_effect"}
            for operation in effect_operations
        )
    return False


def has_extension_branch_from_db(row: dict[str, Any]) -> bool:
    """判断数据库现有技能规则是否包含人工审阅拓展分支。"""
    try:
        damage_rule = json.loads(row.get("damage_rule_json") or "{}")
        hit_rule = json.loads(row.get("hit_rule_json") or "{}")
        effect_operations = json.loads(row.get("effect_operations_json") or "null")
    except json.JSONDecodeError:
        return False
    if not isinstance(damage_rule, dict):
        damage_rule = {}
    if isinstance(effect_operations, list) and any(
        isinstance(operation, dict)
        and operation.get("operation_type") in {"conditional_branch", "dynamic_apply_effect"}
        for operation in effect_operations
    ):
        return True
    if isinstance(hit_rule, dict) and "dynamic_hit_rule" in hit_rule:
        return True
    manual_review = damage_rule.get("manual_review")
    if isinstance(manual_review, dict) and (
        manual_review.get("future_hooks") or manual_review.get("structure_gaps")
    ):
        return True
    return any(
        key in damage_rule
        for key in (
            "response_rule",
            "conditional_branches",
            "dynamic_power_rule",
            "dynamic_damage_rule",
        )
    )


def build_db_coverage_report(
    db_path: Path,
    review_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """将整合后的技能审阅总文件与数据库 active rocom 技能比对。"""
    db_skills = load_db_skill_rows(db_path)
    review_by_id = {str(row["skill_id"]): row for row in review_rows if row.get("skill_id")}

    db_ids = set(db_skills)
    review_ids = set(review_by_id)
    db_extension_ids = {
        skill_id for skill_id, row in db_skills.items() if has_extension_branch_from_db(row)
    }
    review_extension_ids = {
        skill_id for skill_id, row in review_by_id.items() if has_extension_branch_from_review(row)
    }

    name_mismatches = []
    for skill_id in sorted(db_ids & review_ids):
        expected_name = review_by_id[skill_id].get("skill_name")
        actual_name = db_skills[skill_id].get("skill_name")
        if expected_name and actual_name and expected_name != actual_name:
            name_mismatches.append(
                {"skill_id": skill_id, "review_name": expected_name, "db_name": actual_name}
            )

    return {
        "db_path": str(db_path),
        "db_active_rocom_skill_count": len(db_ids),
        "consolidated_review_skill_count": len(review_ids),
        "db_skills_missing_from_consolidated": sorted(db_ids - review_ids),
        "consolidated_skills_missing_from_db": sorted(review_ids - db_ids),
        "name_mismatches": name_mismatches,
        "db_extension_skill_count": len(db_extension_ids),
        "consolidated_extension_skill_count": len(review_extension_ids),
        "db_extension_skills_missing_from_consolidated": sorted(
            db_extension_ids - review_extension_ids
        ),
        "consolidated_extension_skills_missing_from_db": sorted(
            review_extension_ids - db_extension_ids
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description="整合技能人工审阅 JSON 并校验覆盖")
    parser.add_argument("--seed-dir", default="backend/app/seed", help="种子文件目录")
    parser.add_argument("--db-path", default="data/app.db", help="SQLite 数据库路径")
    parser.add_argument("--effects-out", default=DEFAULT_EFFECTS_OUT, help="状态定义总文件名")
    parser.add_argument("--reviews-out", default=DEFAULT_REVIEWS_OUT, help="技能审阅总文件名")
    parser.add_argument("--report-out", default=DEFAULT_REPORT_OUT, help="整合校验报告文件名")
    parser.add_argument(
        "--rewrite-sources",
        action="store_true",
        help="同时用非 ASCII 转义格式重写历史分批文件，并修复已知损坏文本",
    )
    return parser


def main() -> None:
    """CLI 入口。"""
    args = build_parser().parse_args()
    seed_dir = Path(args.seed_dir)
    db_path = Path(args.db_path)

    effect_files = source_files(seed_dir, "manual_skill_effect_definitions")
    review_files = source_files(seed_dir, "manual_skill_rule_reviews")
    if not effect_files and not review_files:
        raise SystemExit(
            "未找到可整合的历史分批源文件；当前仓库默认只保留 *_all_20260612.json "
            "总文件。请先恢复或新增分批源文件后再运行本脚本。"
        )

    effect_rows, effect_summary = consolidate_rows(
        effect_files, "effect_id", "effect", args.rewrite_sources
    )
    review_rows, review_summary = consolidate_rows(
        review_files, "skill_id", "review", args.rewrite_sources
    )

    effects_out = seed_dir / args.effects_out
    reviews_out = seed_dir / args.reviews_out
    write_json(effects_out, effect_rows)
    write_json(reviews_out, review_rows)

    report = {
        "effects": effect_summary | {"output": effects_out.name},
        "reviews": review_summary | {"output": reviews_out.name},
        "db_coverage": build_db_coverage_report(db_path, review_rows),
        "suspicious_strings": {
            "effects": find_suspicious_strings(effect_rows),
            "reviews": find_suspicious_strings(review_rows),
        },
    }
    report_out = seed_dir / args.report_out
    write_json(report_out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
