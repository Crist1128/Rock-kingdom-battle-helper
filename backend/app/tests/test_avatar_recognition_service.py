from __future__ import annotations

from PIL import Image, ImageDraw

from app.recognition.avatar.service import AvatarRecognitionService


def _write_circle_icon(path, color: tuple[int, int, int]) -> None:
    image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 12, 116, 116), fill=(*color, 255))
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
