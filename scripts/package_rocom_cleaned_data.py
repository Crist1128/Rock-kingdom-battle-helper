"""打包可离线导入的 rocom cleaned 数据包。

该脚本只打包 `data/rocom/cleaned` 下的清洗后 JSON，不包含 SQLite 数据库、raw 爬虫缓存、
图片或用户战斗数据。生成的 zip 可发给新用户解压到本机 `data/rocom/cleaned`，再在前端
设置页执行“新用户 / 空库一键初始化”。
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REQUIRED_FILES = (
    "elves.json",
    "skills.json",
    "elf_learnable_skills.json",
    "type_effectiveness_rules.json",
)
OPTIONAL_FILES = ("import_summary.json",)


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器，便于测试和复用。"""
    repo_root = Path(__file__).resolve().parents[1]
    today = datetime.now(UTC).strftime("%Y%m%d")
    parser = argparse.ArgumentParser(description="打包 rocom cleaned JSON 数据包")
    parser.add_argument(
        "--cleaned-dir",
        type=Path,
        default=repo_root / "data" / "rocom" / "cleaned",
        help="cleaned JSON 目录，默认 data/rocom/cleaned",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "data" / "packages" / f"rocom_cleaned_{today}.zip",
        help="输出 zip 路径，默认 data/packages/rocom_cleaned_YYYYMMDD.zip",
    )
    return parser


def package_cleaned_data(cleaned_dir: Path, output: Path) -> dict[str, object]:
    """校验并打包 cleaned 数据文件。"""
    cleaned_dir = cleaned_dir.resolve()
    output = output.resolve()
    missing = [name for name in REQUIRED_FILES if not (cleaned_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"cleaned 数据不完整，缺少：{', '.join(missing)}；目录：{cleaned_dir}"
        )

    files = [cleaned_dir / name for name in REQUIRED_FILES]
    files.extend(cleaned_dir / name for name in OPTIONAL_FILES if (cleaned_dir / name).is_file())

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as zip_file:
        for file_path in files:
            zip_file.write(file_path, arcname=file_path.name)

    return {
        "output": str(output),
        "file_count": len(files),
        "size_bytes": output.stat().st_size,
        "files": [file_path.name for file_path in files],
    }


def main() -> None:
    """命令行入口。"""
    args = build_parser().parse_args()
    result = package_cleaned_data(args.cleaned_dir, args.output)
    print(
        "rocom cleaned 数据包已生成："
        f"{result['output']}，文件数={result['file_count']}，大小={result['size_bytes']} bytes"
    )


if __name__ == "__main__":
    main()
