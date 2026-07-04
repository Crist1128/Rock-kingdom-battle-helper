"""rocom 本地头像 URL 同步工具测试。"""

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.data_pipeline.rocom.avatar_localizer import localize_elf_avatars
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import ElfDefinition
from app.utils.json import dumps_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建头像本地化测试用的独立内存数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _elf(elf_id: str, *, avatar: str = "https://example.test/old.png") -> ElfDefinition:
    return ElfDefinition(
        elf_id=elf_id,
        elf_name=f"{elf_id}_name",
        avatar=avatar,
        element_types_json=dumps_json(["normal"]),
        base_hp_talent=100,
        base_physical_attack_talent=100,
        base_physical_defense_talent=100,
        base_magic_attack_talent=100,
        base_magic_defense_talent=100,
        base_speed_talent=100,
        data_source="biligame_rocom_bwiki",
        data_version="old",
    )


def _write_cleaned_elves(cleaned_dir, rows: list[dict[str, object]]) -> None:
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    (cleaned_dir / "elves.json").write_text(
        json.dumps(rows, ensure_ascii=False),
        encoding="utf-8",
    )


def test_avatar_localizer_dry_run_summary_can_be_rolled_back(
    db_session: Session,
    tmp_path,
) -> None:
    """dry-run 场景下可先得到将更新摘要，然后回滚保持数据库不变。"""
    cleaned_dir = tmp_path / "cleaned"
    image_base_dir = tmp_path / "raw_with_images"
    image_path = image_base_dir / "images" / "sprites" / "elf_a.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake")
    _write_cleaned_elves(
        cleaned_dir,
        [{"elf_id": "elf_a", "elf_name": "测试精灵", "avatar": "images/sprites/elf_a.png"}],
    )
    db_session.add(_elf("elf_a"))
    db_session.commit()

    summary = localize_elf_avatars(
        db_session,
        cleaned_dir=cleaned_dir,
        image_base_dir=image_base_dir,
        url_prefix="/api/v1/assets/rocom/raw_with_images",
    )
    db_session.rollback()

    elf = db_session.get(ElfDefinition, "elf_a")
    assert summary["updated"] == 1
    assert elf is not None
    assert elf.avatar == "https://example.test/old.png"


def test_avatar_localizer_commit_updates_only_avatar(db_session: Session, tmp_path) -> None:
    """本地化工具只应修改 avatar，不应覆盖其它静态字段。"""
    cleaned_dir = tmp_path / "cleaned"
    image_base_dir = tmp_path / "raw_with_images"
    image_path = image_base_dir / "images" / "sprites" / "elf_a.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake")
    _write_cleaned_elves(
        cleaned_dir,
        [{"elf_id": "elf_a", "elf_name": "新名字不应写入", "avatar": "images/sprites/elf_a.png"}],
    )
    db_session.add(_elf("elf_a"))
    db_session.commit()

    summary = localize_elf_avatars(
        db_session,
        cleaned_dir=cleaned_dir,
        image_base_dir=image_base_dir,
        url_prefix="/api/v1/assets/rocom/raw_with_images",
    )
    db_session.commit()

    elf = db_session.get(ElfDefinition, "elf_a")
    assert summary["updated"] == 1
    assert elf is not None
    assert elf.avatar == "/api/v1/assets/rocom/raw_with_images/images/sprites/elf_a.png"
    assert elf.elf_name == "elf_a_name"
    assert elf.data_version == "old"

    second_summary = localize_elf_avatars(
        db_session,
        cleaned_dir=cleaned_dir,
        image_base_dir=image_base_dir,
        url_prefix="/api/v1/assets/rocom/raw_with_images",
    )
    assert second_summary["unchanged"] == 1


def test_avatar_localizer_skips_missing_image_file(db_session: Session, tmp_path) -> None:
    """cleaned 指向不存在的本地图片时应跳过，避免写入坏链接。"""
    cleaned_dir = tmp_path / "cleaned"
    image_base_dir = tmp_path / "raw_with_images"
    image_base_dir.mkdir()
    _write_cleaned_elves(
        cleaned_dir,
        [{"elf_id": "elf_a", "elf_name": "测试精灵", "avatar": "images/sprites/missing.png"}],
    )
    db_session.add(_elf("elf_a"))
    db_session.commit()

    summary = localize_elf_avatars(
        db_session,
        cleaned_dir=cleaned_dir,
        image_base_dir=image_base_dir,
        url_prefix="/api/v1/assets/rocom/raw_with_images",
    )

    elf = db_session.get(ElfDefinition, "elf_a")
    assert summary["skipped_missing_file"] == 1
    assert summary["updated"] == 0
    assert elf is not None
    assert elf.avatar == "https://example.test/old.png"
