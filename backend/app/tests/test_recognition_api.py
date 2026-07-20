from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.core.config import settings
from app.data_pipeline.rocom.avatar_recognizer import DEFAULT_ENEMY_SLOT_BOXES_XYXY
from app.db.base import Base
from app.db.session import get_db
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import estimate as _estimate_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import ElfDefinition
from app.utils.json import dumps_json


@pytest.fixture()
def api_client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """创建隔离的识别 API 客户端、头像模板目录和内存数据库。"""
    rocom_dir = tmp_path / "rocom"
    icons_dir = rocom_dir / "recognition" / "elf_icons_128"
    icons_dir.mkdir(parents=True)
    _write_circle_icon(icons_dir / "001_red.png", (220, 30, 30))
    _write_circle_icon(icons_dir / "002_green.png", (30, 220, 30))
    monkeypatch.setattr(settings, "rocom_data_dir", str(rocom_dir))

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    Base.metadata.create_all(engine)
    with TestingSessionLocal() as session:
        session.add_all(
            [
                ElfDefinition(
                    elf_id="rocom_elf_0001_test",
                    elf_name="red",
                    avatar="/avatars/red.png",
                    element_types_json=dumps_json(["fire"]),
                    base_hp_talent=100,
                    base_physical_attack_talent=100,
                    base_physical_defense_talent=100,
                    base_magic_attack_talent=100,
                    base_magic_defense_talent=100,
                    base_speed_talent=100,
                    data_version="test",
                ),
                ElfDefinition(
                    elf_id="rocom_elf_0002_test",
                    elf_name="green",
                    avatar="/avatars/green.png",
                    element_types_json=dumps_json(["grass"]),
                    base_hp_talent=100,
                    base_physical_attack_talent=100,
                    base_physical_defense_talent=100,
                    base_magic_attack_talent=100,
                    base_magic_defense_talent=100,
                    base_speed_talent=100,
                    data_version="test",
                ),
            ]
        )
        session.commit()

    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    def override_get_db() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _write_circle_icon(path, color: tuple[int, int, int]) -> None:
    image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 12, 116, 116), fill=(*color, 255))
    image.save(path)


def _build_default_size_screenshot() -> bytes:
    image = Image.new("RGBA", (1150, 643), (20, 20, 20, 255))
    icon = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    draw.ellipse((12, 12, 116, 116), fill=(220, 30, 30, 255))
    x1, y1, x2, y2 = DEFAULT_ENEMY_SLOT_BOXES_XYXY[0]
    image.alpha_composite(icon.resize((x2 - x1, y2 - y1)), (x1, y1))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_recognition_api_returns_confirmable_candidates(api_client: TestClient) -> None:
    """上传截图后应返回每个敌方槽位的候选，并把模板候选映射到数据库精灵。"""
    response = api_client.post(
        "/api/v1/recognition/enemy-lineup?top_k=2",
        files={"file": ("screenshot.png", _build_default_size_screenshot(), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_image_size"] == [1150, 643]
    assert body["icon_template_count"] == 2
    assert len(body["slots"]) == 6
    first_candidate = body["slots"][0]["candidates"][0]
    assert first_candidate["dex_no"] == "001"
    assert first_candidate["icon_url"].endswith("/001_red.png")
    assert first_candidate["matched_elves"][0]["elf_id"] == "rocom_elf_0001_test"
    assert "不会自动写入阵容" in body["warnings"][0]


def test_recognition_api_rejects_invalid_image(api_client: TestClient) -> None:
    """非图片上传应返回 400，避免进入模板识别流程。"""
    response = api_client.post(
        "/api/v1/recognition/enemy-lineup",
        files={"file": ("bad.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 400


def test_recognition_api_can_skip_debug_artifacts(api_client: TestClient) -> None:
    """调用方可关闭调试图片落盘，避免不需要时产生本地文件。"""
    response = api_client.post(
        "/api/v1/recognition/enemy-lineup?top_k=2&include_debug=false",
        files={"file": ("screenshot.png", _build_default_size_screenshot(), "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["debug_artifacts"] is None
