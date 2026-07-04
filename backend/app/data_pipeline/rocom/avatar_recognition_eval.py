"""敌方头像识别回归评估与本地确认样本导出工具。

用途：

1. 从截图文件名解析形如 `精灵名1_精灵名2...` 的标准答案；
2. 运行当前头像识别算法，输出每槽正确答案 rank 和 Top-K 命中率；
3. 可选把已标注截图中的槽位裁图导出到 `elf_icons_128_confirmed`，作为人工确认的敌方朝向
   多模板样本。默认 dry-run，只有传入 `--commit-export` 才会写文件。

该工具只读截图和模板素材，不写数据库。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

from app.data_pipeline.rocom.avatar_recognizer import (
    SlotRecognition,
    recognition_to_dict,
    recognize_enemy_lineup,
)

ANSWER_TOKEN_PATTERN = re.compile(r"(?P<name>.+?)(?P<slot>[1-6])$")
TEMPLATE_FILENAME_PATTERN = re.compile(
    r"^(?P<dex_no>\d{3})_(?P<name>.+)\.(?:png|jpg|jpeg|webp)$",
    re.I,
)


def parse_answers_from_filename(path: str | Path) -> list[str]:
    """从文件名解析 1-6 号槽标准答案。"""
    stem = Path(path).stem
    answers: dict[int, str] = {}
    for token in stem.split("_"):
        match = ANSWER_TOKEN_PATTERN.fullmatch(token)
        if match is None:
            continue
        slot = int(match.group("slot"))
        answers[slot] = match.group("name")
    return [answers[index] for index in range(1, 7) if index in answers]


def _candidate_names(result: SlotRecognition) -> list[str]:
    """返回候选精灵名列表。"""
    return [candidate.elf_name for candidate in result.candidates]


def build_eval_report(results: list[SlotRecognition], answers: list[str]) -> dict[str, Any]:
    """生成识别评估摘要。"""
    rows: list[dict[str, Any]] = []
    top1_hits = 0
    top3_hits = 0
    top5_hits = 0
    for result, answer in zip(results, answers, strict=False):
        names = _candidate_names(result)
        rank = names.index(answer) + 1 if answer in names else None
        rows.append(
            {
                "slot_index": result.slot_index,
                "answer": answer,
                "rank": rank,
                "top1_hit": rank == 1,
                "top3_hit": rank is not None and rank <= 3,
                "top5_hit": rank is not None and rank <= 5,
                "top_candidates": names,
            }
        )
        top1_hits += 1 if rank == 1 else 0
        top3_hits += 1 if rank is not None and rank <= 3 else 0
        top5_hits += 1 if rank is not None and rank <= 5 else 0
    total = len(rows)
    return {
        "total_slots": total,
        "top1_hits": top1_hits,
        "top3_hits": top3_hits,
        "top5_hits": top5_hits,
        "top1_accuracy": round(top1_hits / total, 4) if total else 0.0,
        "top3_accuracy": round(top3_hits / total, 4) if total else 0.0,
        "top5_accuracy": round(top5_hits / total, 4) if total else 0.0,
        "slots": rows,
    }


def _dex_no_by_name(icons_dir: Path) -> dict[str, str]:
    """按模板文件名建立精灵名到图鉴编号的映射。"""
    mapping: dict[str, str] = {}
    for path in sorted(icons_dir.iterdir()):
        if not path.is_file():
            continue
        match = TEMPLATE_FILENAME_PATTERN.match(path.name)
        if match is None:
            continue
        mapping.setdefault(match.group("name"), match.group("dex_no"))
    return mapping


def export_confirmed_crops(
    screenshot_path: str | Path,
    results: list[SlotRecognition],
    answers: list[str],
    icons_dir: str | Path,
    output_dir: str | Path,
    *,
    commit: bool,
    overwrite: bool,
) -> dict[str, Any]:
    """把带答案截图中的槽位裁图导出为本地确认模板。"""
    icons_root = Path(icons_dir)
    target_root = Path(output_dir)
    dex_by_name = _dex_no_by_name(icons_root)
    screenshot = Image.open(screenshot_path).convert("RGBA")
    summary: dict[str, Any] = {
        "transaction": "committed" if commit else "dry_run",
        "target_dir": str(target_root),
        "planned": [],
        "skipped": [],
        "written": 0,
    }

    for result, answer in zip(results, answers, strict=False):
        dex_no = dex_by_name.get(answer)
        if dex_no is None:
            summary["skipped"].append(
                {
                    "slot_index": result.slot_index,
                    "answer": answer,
                    "reason": "answer_not_found_in_base_templates",
                }
            )
            continue
        target = target_root / f"{dex_no}_{answer}.png"
        if target.exists() and not overwrite:
            summary["skipped"].append(
                {
                    "slot_index": result.slot_index,
                    "answer": answer,
                    "target": str(target),
                    "reason": "target_exists",
                }
            )
            continue
        summary["planned"].append(
            {
                "slot_index": result.slot_index,
                "answer": answer,
                "target": str(target),
                "box": result.box.xyxy,
            }
        )
        if commit:
            target.parent.mkdir(parents=True, exist_ok=True)
            screenshot.crop(result.box.xyxy).save(target)
            summary["written"] += 1
    return summary


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description="评估敌方头像识别效果并可导出确认样本")
    parser.add_argument("--image", required=True, help="带答案文件名的截图路径")
    parser.add_argument(
        "--icons-dir",
        default="../data/rocom/recognition/elf_icons_128",
        help="基础头像模板目录",
    )
    parser.add_argument("--top-k", type=int, default=10, help="每槽返回候选数量")
    parser.add_argument("--output-json", help="评估报告 JSON 输出路径")
    parser.add_argument("--recognition-json", help="原始识别结果 JSON 输出路径")
    parser.add_argument(
        "--export-confirmed-dir",
        default="../data/rocom/recognition/elf_icons_128_confirmed",
        help="确认样本导出目录；默认仅 dry-run",
    )
    parser.add_argument("--commit-export", action="store_true", help="实际写入确认样本")
    parser.add_argument("--overwrite", action="store_true", help="导出确认样本时覆盖同名文件")
    return parser


def main() -> None:
    """CLI 入口。"""
    args = build_parser().parse_args()
    answers = parse_answers_from_filename(args.image)
    if len(answers) != 6:
        raise ValueError("截图文件名中未解析到完整 1-6 槽答案")

    results = recognize_enemy_lineup(args.image, args.icons_dir, top_k=args.top_k)
    report = build_eval_report(results, answers)
    report["answers"] = answers
    report["confirmed_export"] = export_confirmed_crops(
        args.image,
        results,
        answers,
        args.icons_dir,
        args.export_confirmed_dir,
        commit=args.commit_export,
        overwrite=args.overwrite,
    )

    if args.recognition_json:
        recognition_path = Path(args.recognition_json)
        recognition_path.parent.mkdir(parents=True, exist_ok=True)
        recognition_path.write_text(
            json.dumps(recognition_to_dict(results), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
