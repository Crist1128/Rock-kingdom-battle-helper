from __future__ import annotations

from PIL import Image, ImageDraw

from app.recognition.avatar.service import AvatarRecognitionService


def _write_circle_icon(path, color: tuple[int, int, int]) -> None:
    image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 12, 116, 116), fill=(*color, 255))
    image.save(path)


def _write_triangle_icon(path, color: tuple[int, int, int]) -> None:
    image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.polygon(((64, 8), (118, 118), (10, 118)), fill=(*color, 255))
    image.save(path)


def test_avatar_recognition_service_recognizes_pre_cropped_avatar(tmp_path) -> None:
    """统一头像服务应只依赖裁图本身，不依赖准备阶段槽位定位。"""
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    _write_circle_icon(icons_dir / "001_red.png", (220, 30, 30))
    _write_circle_icon(icons_dir / "002_green.png", (30, 220, 30))

    service = AvatarRecognitionService(icons_dir)
    result = service.recognize_crop(Image.open(icons_dir / "002_green.png"), top_k=1)

    assert result.engine == "avatar_feature_index_v1"
    assert result.template_count == 2
    assert result.candidates[0].dex_no == "002"
    assert result.candidates[0].elf_name == "green"


def test_avatar_recognition_service_excludes_confirmed_samples_by_default(tmp_path) -> None:
    """少量人工确认样本默认不能进入线上识别索引，避免污染全局结果。"""
    icons_dir = tmp_path / "icons"
    confirmed_dir = tmp_path / "icons_confirmed"
    icons_dir.mkdir()
    confirmed_dir.mkdir()
    _write_circle_icon(icons_dir / "001_red.png", (220, 30, 30))
    _write_circle_icon(confirmed_dir / "002_green.png", (30, 220, 30))

    service = AvatarRecognitionService(icons_dir)

    assert service.template_count == 1


def test_avatar_recognition_service_prefers_clean_foreground_over_noisy_background(
    tmp_path,
) -> None:
    """新高清透明头像模板应主要按主体前景识别，而不是被截图背景颜色主导。"""
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    # 两个模板使用相同主色，只有前景形状不同；用于验证形状/前景权重确实参与排序。
    _write_circle_icon(icons_dir / "001_blue_circle.png", (40, 140, 230))
    _write_triangle_icon(icons_dir / "002_blue_triangle.png", (40, 140, 230))

    noisy_crop = Image.new("RGBA", (128, 128), (12, 12, 12, 255))
    draw = ImageDraw.Draw(noisy_crop)
    # 模拟准备页头像框的橙色描边、暗纹和背景干扰。
    draw.rectangle((0, 0, 127, 127), outline=(214, 122, 35, 255), width=8)
    for y in range(0, 128, 12):
        draw.line((0, y, 127, y), fill=(45, 36, 28, 255), width=2)
    triangle = Image.open(icons_dir / "002_blue_triangle.png").convert("RGBA")
    noisy_crop.alpha_composite(triangle, (0, 0))

    service = AvatarRecognitionService(icons_dir)
    result = service.recognize_crop(noisy_crop, top_k=2)

    assert result.candidates[0].dex_no == "002"
    assert result.candidates[0].elf_name == "blue_triangle"


def test_avatar_recognition_service_refocuses_small_offset_avatar(tmp_path) -> None:
    """头像裁片主体偏小且带 UI 背景时，应生成前景聚焦变体再匹配。"""
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    _write_circle_icon(icons_dir / "001_pink_circle.png", (235, 135, 178))
    _write_triangle_icon(icons_dir / "002_green_triangle.png", (40, 210, 90))

    crop = Image.new("RGBA", (128, 128), (16, 13, 11, 255))
    draw = ImageDraw.Draw(crop)
    draw.rectangle((0, 0, 127, 127), outline=(214, 122, 35, 255), width=14)
    small_icon = Image.open(icons_dir / "001_pink_circle.png").resize((72, 72))
    crop.alpha_composite(small_icon, (26, 28))

    service = AvatarRecognitionService(icons_dir)
    result = service.recognize_crop(crop, top_k=1)

    assert result.candidates[0].dex_no == "001"
    assert result.candidates[0].elf_name == "pink_circle"


def test_avatar_recognition_service_reuses_disk_feature_cache(tmp_path) -> None:
    """模板预处理特征应写入磁盘缓存，后续服务实例可复用缓存加快启动。"""
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    _write_circle_icon(icons_dir / "001_red.png", (220, 30, 30))
    _write_triangle_icon(icons_dir / "002_blue_triangle.png", (40, 140, 230))

    first_service = AvatarRecognitionService(icons_dir)
    assert first_service.template_count == 2

    cache_files = list(tmp_path.glob(".icons_*_feature_index_v4.npz"))
    assert len(cache_files) == 1

    second_service = AvatarRecognitionService(icons_dir)
    result = second_service.recognize_crop(Image.open(icons_dir / "001_red.png"), top_k=1)

    assert second_service.template_count == 2
    assert result.candidates[0].dex_no == "001"
