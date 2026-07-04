from __future__ import annotations

import json

from PIL import Image, ImageDraw

from app.data_pipeline.rocom.avatar_recognition_eval import parse_answers_from_filename
from app.data_pipeline.rocom.avatar_recognizer import (
    AvatarBox,
    default_enemy_slot_boxes,
    load_avatar_templates,
    load_boxes_from_json,
    locate_enemy_avatar_boxes,
    match_avatar_crop,
    recognition_to_dict,
    recognize_enemy_lineup,
)


def _write_circle_icon(path, color: tuple[int, int, int]) -> None:
    image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 12, 116, 116), fill=(*color, 255))
    image.save(path)


def test_match_avatar_crop_prefers_nearest_template(tmp_path) -> None:
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    _write_circle_icon(icons_dir / "001_red.png", (220, 30, 30))
    _write_circle_icon(icons_dir / "002_green.png", (30, 220, 30))
    _write_circle_icon(icons_dir / "003_blue.png", (30, 30, 220))

    templates = load_avatar_templates(icons_dir)
    crop = Image.open(icons_dir / "002_green.png")
    candidates = match_avatar_crop(crop, templates, top_k=2)

    assert candidates[0].dex_no == "002"
    assert candidates[0].elf_name == "green"
    assert candidates[0].score >= candidates[1].score


def test_recognize_enemy_lineup_with_custom_box(tmp_path) -> None:
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    _write_circle_icon(icons_dir / "001_red.png", (220, 30, 30))
    _write_circle_icon(icons_dir / "002_green.png", (30, 220, 30))

    screenshot = Image.new("RGBA", (120, 80), (20, 20, 20, 255))
    screenshot.alpha_composite(Image.open(icons_dir / "001_red.png").resize((40, 40)), (10, 20))
    screenshot_path = tmp_path / "screenshot.png"
    screenshot.save(screenshot_path)

    results = recognize_enemy_lineup(
        screenshot_path=screenshot_path,
        icons_dir=icons_dir,
        boxes=[AvatarBox(10, 20, 50, 60)],
        top_k=1,
    )
    payload = recognition_to_dict(results)

    assert payload["slots"][0]["slot_index"] == 1
    assert payload["slots"][0]["candidates"][0]["dex_no"] == "001"


def test_default_enemy_slot_boxes_scale_with_image_size() -> None:
    boxes = default_enemy_slot_boxes((2300, 1286))

    assert boxes[0] == AvatarBox(2050, 258, 2178, 386)
    assert boxes[-1] == AvatarBox(2050, 850, 2178, 978)


def test_locate_enemy_avatar_boxes_prefers_black_slot_detection() -> None:
    """黑色槽位检测应能在槽位整体偏移时动态推算头像框。"""
    image = Image.new("RGB", (1150, 643), (180, 180, 180))
    draw = ImageDraw.Draw(image)
    slot_boxes = [
        AvatarBox(900, 132 + index * 59, 1092, 180 + index * 59)
        for index in range(6)
    ]
    for slot in slot_boxes:
        draw.rounded_rectangle(slot.xyxy, radius=18, fill=(18, 18, 18))
        draw.rectangle((slot.x1 + 35, slot.y2 - 13, slot.x1 + 115, slot.y2 - 8), fill=(40, 210, 70))

    localization = locate_enemy_avatar_boxes(image)

    assert localization.method == "black_slot"
    assert localization.confidence >= 0.8
    assert len(localization.avatar_boxes) == 6
    assert localization.avatar_boxes[0].x1 <= 1032
    assert localization.avatar_boxes[0].x2 >= 1085


def test_load_boxes_from_json_supports_xyxy_and_xywh(tmp_path) -> None:
    path = tmp_path / "boxes.json"
    path.write_text(
        json.dumps(
            [
                {"x1": 1, "y1": 2, "x2": 3, "y2": 4},
                {"x": 10, "y": 20, "w": 30, "h": 40},
            ]
        ),
        encoding="utf-8",
    )

    assert load_boxes_from_json(path) == [
        AvatarBox(1, 2, 3, 4),
        AvatarBox(10, 20, 40, 60),
    ]


def test_load_avatar_templates_excludes_confirmed_sibling_dir_by_default(tmp_path) -> None:
    icons_dir = tmp_path / "icons"
    confirmed_dir = tmp_path / "icons_confirmed"
    icons_dir.mkdir()
    confirmed_dir.mkdir()
    _write_circle_icon(icons_dir / "001_red.png", (220, 30, 30))
    _write_circle_icon(confirmed_dir / "002_green.png", (30, 220, 30))

    templates = load_avatar_templates(icons_dir)

    template_flags = [
        (template.dex_no, template.elf_name, template.is_confirmed) for template in templates
    ]
    assert template_flags == [("001", "red", False)]


def test_load_avatar_templates_can_explicitly_include_confirmed_sibling_dir(tmp_path) -> None:
    icons_dir = tmp_path / "icons_explicit"
    confirmed_dir = tmp_path / "icons_explicit_confirmed"
    icons_dir.mkdir()
    confirmed_dir.mkdir()
    _write_circle_icon(icons_dir / "001_red.png", (220, 30, 30))
    _write_circle_icon(confirmed_dir / "002_green.png", (30, 220, 30))

    templates = load_avatar_templates(icons_dir, include_confirmed_templates=True)

    template_flags = [
        (template.dex_no, template.elf_name, template.is_confirmed) for template in templates
    ]
    assert template_flags == [
        ("001", "red", False),
        ("002", "green", True),
    ]


def test_parse_answers_from_filename() -> None:
    answers = parse_answers_from_filename(
        "战斗准备测试图片_雪影娃娃1_寂灭骨龙2_尖嘴狐仙3_月牙雪熊4_龙息帕尔5_翠顶夫人6.png"
    )

    assert answers == ["雪影娃娃", "寂灭骨龙", "尖嘴狐仙", "月牙雪熊", "龙息帕尔", "翠顶夫人"]
