from __future__ import annotations

import json
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

import app.recognition.avatar.full_library as full_library
from app.recognition.avatar.full_library import (
    build_slot_boxes,
    get_avatar_recognizer,
    load_avatar_assets,
    write_outputs,
)


def _write_circle_icon(path: Path, color: tuple[int, int, int]) -> None:
    image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((14, 14, 114, 114), fill=(*color, 255))
    image.save(path)


def _write_square_icon(path: Path, color: tuple[int, int, int]) -> None:
    image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((18, 18, 110, 110), radius=10, fill=(*color, 255))
    image.save(path)


def _recolor_icon(icon: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    rgba = icon.convert("RGBA")
    alpha = rgba.getchannel("A")
    recolored = Image.new("RGBA", rgba.size, (*color, 255))
    recolored.putalpha(alpha)
    return recolored


def _build_screenshot(icons_dir: Path) -> Image.Image:
    screenshot = Image.new("RGBA", (1147, 643), (20, 20, 20, 255))
    boxes = build_slot_boxes(screenshot.size)
    icon_paths = sorted(icons_dir.glob("*.png"))
    for index, box in enumerate(boxes, start=1):
        icon = Image.open(icon_paths[index - 1]).convert("RGBA")
        icon = ImageOps.mirror(icon)
        icon_size = box.width - 14
        icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
        screenshot.alpha_composite(icon, (box.x1 + 7, box.y1 + 7))
    draw = ImageDraw.Draw(screenshot)
    draw.rectangle((0, 0, 420, 60), fill=(0, 0, 0, 255))
    draw.text((12, 12), "enemy lineup name text should be ignored", fill=(255, 255, 255, 255))
    return screenshot


def test_alpha_template_recognizer_matches_screenshot_and_writes_outputs(tmp_path: Path) -> None:
    """应能按透明模板库识别 6 个槽位，并输出调试产物。"""
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    for index, color in enumerate(
        [
            (220, 30, 30),
            (30, 220, 30),
            (30, 80, 220),
            (220, 180, 30),
            (180, 30, 220),
            (30, 210, 200),
        ],
        start=1,
    ):
        _write_circle_icon(icons_dir / f"{index:03d}_icon.png", color)

    screenshot = _build_screenshot(icons_dir)
    screenshot_path = tmp_path / "screenshot.png"
    screenshot.save(screenshot_path)

    output_dir = tmp_path / "output"
    result = write_outputs(screenshot_path, icons_dir, output_dir)

    assert result.asset_count == 6
    assert [slot.top1.label for slot in result.slots] == [
        f"{index:03d}_icon" for index in range(1, 7)
    ]
    assert (output_dir / "results.json").is_file()
    assert (output_dir / "results.csv").is_file()
    assert (output_dir / "annotated_recognition.png").is_file()
    assert (output_dir / "recognition_contact_sheet.png").is_file()
    assert (output_dir / "comparison" / "slot_1_detail.png").is_file()
    assert (output_dir / "comparison" / "slot_1_top5.png").is_file()
    assert len(list((output_dir / "slot_crops").glob("slot_*.png"))) == 6
    assert len(list((output_dir / "matched_assets").glob("slot_*"))) == 6

    payload = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    assert payload["method"].startswith("pixel-only alpha-masked template matching")
    assert payload["results"][0]["top1"]["confidence_level"] in {"high", "medium", "low"}


def test_alpha_template_recognizer_is_independent_of_template_filenames(
    tmp_path: Path,
) -> None:
    """重命名素材后，视觉匹配结果应保持同一批模板内容。"""
    source_dir = tmp_path / "source"
    renamed_dir = tmp_path / "renamed"
    source_dir.mkdir()
    renamed_dir.mkdir()
    for index, color in enumerate(
        [
            (220, 30, 30),
            (30, 220, 30),
            (30, 80, 220),
            (220, 180, 30),
            (180, 30, 220),
            (30, 210, 200),
        ],
        start=1,
    ):
        _write_circle_icon(source_dir / f"{index:03d}_icon.png", color)
        _write_circle_icon(renamed_dir / f"random_{index}.png", color)

    screenshot = _build_screenshot(source_dir)
    screenshot_path = tmp_path / "screenshot.png"
    screenshot.save(screenshot_path)

    source_result = write_outputs(screenshot_path, source_dir, tmp_path / "out_source")
    renamed_result = write_outputs(screenshot_path, renamed_dir, tmp_path / "out_renamed")

    assert [slot.top1.sha256 for slot in source_result.slots] == [
        slot.top1.sha256 for slot in renamed_result.slots
    ]
    assert [slot.top1.label for slot in source_result.slots] != [
        slot.top1.label for slot in renamed_result.slots
    ]


def test_chroma_color_shift_keeps_shape_identity_and_shiny_template_can_win(
    tmp_path: Path,
) -> None:
    """Color-shifted chroma should keep identity; dedicated recolor templates still win."""
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    _write_circle_icon(icons_dir / "001_base_circle.png", (220, 30, 30))
    _write_square_icon(icons_dir / "002_orange_square.png", (245, 145, 35))
    _write_circle_icon(icons_dir / "003_blue_circle.png", (35, 80, 230))
    for index, color in enumerate(
        [(220, 180, 30), (180, 30, 220), (30, 210, 200)],
        start=4,
    ):
        _write_square_icon(icons_dir / f"{index:03d}_filler.png", color)

    screenshot = Image.new("RGBA", (1147, 643), (20, 20, 20, 255))
    boxes = build_slot_boxes(screenshot.size)
    icon_paths = [
        icons_dir / "001_base_circle.png",
        icons_dir / "003_blue_circle.png",
        icons_dir / "002_orange_square.png",
        icons_dir / "004_filler.png",
        icons_dir / "005_filler.png",
        icons_dir / "006_filler.png",
    ]
    for index, box in enumerate(boxes):
        icon = Image.open(icon_paths[index]).convert("RGBA")
        if index == 0:
            icon = _recolor_icon(icon, (245, 145, 35))
        icon = ImageOps.mirror(icon)
        icon_size = box.width - 14
        icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
        screenshot.alpha_composite(icon, (box.x1 + 7, box.y1 + 7))

    screenshot_path = tmp_path / "chroma_screenshot.png"
    screenshot.save(screenshot_path)

    result = write_outputs(screenshot_path, icons_dir, tmp_path / "output")

    assert result.slots[0].top1.label == "001_base_circle"
    assert result.slots[1].top1.label == "003_blue_circle"
    assert result.slots[0].top1.edge_score >= result.slots[0].top1.gray_score * 0.5


def test_recognizer_exhaustively_scores_full_template_library(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Accuracy regression: do not truncate templates before precise matching."""
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    for index in range(55):
        color = (
            30 + index * 37 % 200,
            40 + index * 53 % 190,
            50 + index * 71 % 180,
        )
        _write_circle_icon(icons_dir / f"{index + 1:03d}_icon.png", color)

    screenshot = _build_screenshot(icons_dir)
    screenshot_path = tmp_path / "screenshot.png"
    screenshot.save(screenshot_path)

    original_score = full_library._template_score_on_roi
    score_calls = {"count": 0}

    def wrapped_score(slot_roi, slot, variant):
        score_calls["count"] += 1
        return original_score(slot_roi, slot, variant)

    get_avatar_recognizer.cache_clear()
    monkeypatch.setattr(full_library, "_template_score_on_roi", wrapped_score)

    result = write_outputs(screenshot_path, icons_dir, tmp_path / "output")

    expected_calls = 6 * len(list(icons_dir.glob("*.png"))) * len(
        full_library.AlphaTemplateRecognizer._candidate_sizes(screenshot.size)
    )
    assert score_calls["count"] == expected_calls
    assert [slot.top1.label for slot in result.slots] == [
        f"{index:03d}_icon" for index in range(1, 7)
    ]
    for slot in result.slots:
        visual_ids = [candidate.visual_id for candidate in slot.top5]
        assert len(visual_ids) == len(set(visual_ids))


def test_alpha_template_recognizer_supports_zip_input_and_skips_traversal(tmp_path: Path) -> None:
    """ZIP 素材源应可加载，并忽略路径穿越条目。"""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    _write_circle_icon(source_dir / "001_icon.png", (220, 30, 30))
    _write_circle_icon(source_dir / "002_icon.png", (30, 220, 30))
    zip_path = tmp_path / "icons.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(source_dir / "001_icon.png", arcname="folder/001_icon.png")
        archive.write(source_dir / "002_icon.png", arcname="nested/002_icon.png")
        archive.writestr("../evil.png", b"evil")

    assets = load_avatar_assets(zip_path)
    assert len(assets) == 2
    assert {asset.label for asset in assets} == {"001_icon", "002_icon"}


def test_alpha_template_recognizer_supports_unicode_paths(tmp_path: Path) -> None:
    """中文目录和中文文件名都应可读取，避免 Windows 路径下的 OpenCV 读图失败。"""
    icons_dir = tmp_path / "头像素材目录"
    icons_dir.mkdir()
    for name, color in [
        ("001_圣光.png", (220, 30, 30)),
        ("002_逆风.png", (30, 220, 30)),
        ("003_喵靓.png", (30, 80, 220)),
        ("004_恶魔狼.png", (220, 180, 30)),
        ("005_彩蝶鲨.png", (180, 30, 220)),
        ("006_音速犬.png", (30, 210, 200)),
    ]:
        _write_circle_icon(icons_dir / name, color)

    screenshot = _build_screenshot(icons_dir)
    screenshot_path = tmp_path / "准备页截图.png"
    screenshot.save(screenshot_path)

    output_dir = tmp_path / "输出目录"
    result = write_outputs(screenshot_path, icons_dir, output_dir)

    assert result.asset_count == 6
    assert all(slot.top1 is not None for slot in result.slots)


def test_cached_recognizer_reuses_loaded_assets(tmp_path: Path, monkeypatch) -> None:
    """同目录重复获取识别器时，应复用进程级缓存。"""
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    _write_circle_icon(icons_dir / "001_icon.png", (220, 30, 30))
    _write_circle_icon(icons_dir / "002_icon.png", (30, 220, 30))

    original_load_avatar_assets = load_avatar_assets
    calls = {"count": 0}

    def wrapped_load_avatar_assets(source):
        calls["count"] += 1
        return original_load_avatar_assets(source)

    get_avatar_recognizer.cache_clear()
    monkeypatch.setattr(
        "app.recognition.avatar.full_library.load_avatar_assets",
        wrapped_load_avatar_assets,
    )

    recognizer_one = get_avatar_recognizer(icons_dir)
    recognizer_two = get_avatar_recognizer(icons_dir)

    assert recognizer_one is recognizer_two
    assert calls["count"] == 1
