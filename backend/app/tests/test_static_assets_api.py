"""本地 rocom 图片资源接口测试。"""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_rocom_asset_api_serves_image_file(tmp_path, monkeypatch) -> None:
    """合法图片路径应从配置的 rocom 数据目录读取并返回。"""
    rocom_dir = tmp_path / "rocom"
    image_dir = rocom_dir / "raw_with_images" / "images" / "sprites"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "elf.png"
    image_path.write_bytes(b"fake-png")
    monkeypatch.setattr(settings, "rocom_data_dir", str(rocom_dir))

    client = TestClient(app)
    response = client.get("/api/v1/assets/rocom/raw_with_images/images/sprites/elf.png")

    assert response.status_code == 200
    assert response.content == b"fake-png"


def test_rocom_asset_api_rejects_path_traversal(tmp_path, monkeypatch) -> None:
    """目录穿越路径不应读取 rocom 数据目录外的文件。"""
    rocom_dir = tmp_path / "rocom"
    rocom_dir.mkdir()
    (tmp_path / "secret.png").write_bytes(b"secret")
    monkeypatch.setattr(settings, "rocom_data_dir", str(rocom_dir))

    client = TestClient(app)
    response = client.get("/api/v1/assets/rocom/%2E%2E/secret.png")

    assert response.status_code in {400, 404}


def test_rocom_asset_api_rejects_non_image_file(tmp_path, monkeypatch) -> None:
    """接口只暴露图片扩展名，避免把 JSON/数据库等文件当静态资源暴露。"""
    rocom_dir = tmp_path / "rocom"
    rocom_dir.mkdir()
    (rocom_dir / "image_urls.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(settings, "rocom_data_dir", str(rocom_dir))

    client = TestClient(app)
    response = client.get("/api/v1/assets/rocom/image_urls.json")

    assert response.status_code == 400
