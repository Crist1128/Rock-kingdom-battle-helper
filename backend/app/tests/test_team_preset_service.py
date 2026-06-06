"""配队预设服务测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import static as _static_models  # noqa: F401
from app.models.static import ElfDefinition, NatureDefinition, PlayerElfBuild
from app.schemas.team_preset import TeamPresetCreate
from app.services.team_preset_service import TeamPresetService
from app.utils.json import dumps_json


@pytest.fixture()
def session_factory() -> Iterator[sessionmaker[Session]]:
    """创建隔离内存数据库。"""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_create_self_team_preset_with_build_slots(
    session_factory: sessionmaker[Session],
) -> None:
    """己方配队保存 build_id，并在输出中冗余展示精灵名和配置名。"""
    with session_factory() as session:
        _seed_rules(session)

        result = TeamPresetService(session).create_preset(
            TeamPresetCreate(
                preset_name="己方测试队",
                side_usage="self",
                source_type="custom",
                slots=[
                    {"slot_index": 0, "elf_id": "elf_alpha", "build_id": "build_alpha"},
                    {"slot_index": 1, "elf_id": "elf_beta", "build_id": "build_beta"},
                ],
            )
        )

        assert result.preset_name == "己方测试队"
        assert result.side_usage == "self"
        assert [slot.slot_index for slot in result.slots] == [0, 1]
        assert result.slots[0].elf_name == "甲"
        assert result.slots[0].build_name == "甲配置"


def test_create_enemy_popular_team_without_build_id(
    session_factory: sessionmaker[Session],
) -> None:
    """敌方热门阵容可以只保存 elf_id，不需要己方配置。"""
    with session_factory() as session:
        _seed_rules(session)

        result = TeamPresetService(session).create_preset(
            TeamPresetCreate(
                preset_name="敌方热门队",
                side_usage="enemy",
                source_type="popular",
                slots=[
                    {"slot_index": 0, "elf_id": "elf_alpha"},
                    {"slot_index": 1, "elf_id": "elf_beta"},
                ],
            )
        )

        assert result.source_type == "popular"
        assert [slot.build_id for slot in result.slots] == [None, None]


def test_self_team_requires_matching_build_elf(
    session_factory: sessionmaker[Session],
) -> None:
    """己方配队槽位中的 build_id 必须属于同一个 elf_id。"""
    with session_factory() as session:
        _seed_rules(session)

        with pytest.raises(ValueError, match="build_id 与 elf_id 不一致"):
            TeamPresetService(session).create_preset(
                TeamPresetCreate(
                    preset_name="错误配队",
                    side_usage="self",
                    source_type="custom",
                    slots=[{"slot_index": 0, "elf_id": "elf_beta", "build_id": "build_alpha"}],
                )
            )


def _seed_rules(session: Session) -> None:
    session.add_all(
        [
            ElfDefinition(
                elf_id="elf_alpha",
                elf_name="甲",
                avatar="",
                element_types_json=dumps_json(["fire"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
            ElfDefinition(
                elf_id="elf_beta",
                elf_name="乙",
                avatar="",
                element_types_json=dumps_json(["water"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
            NatureDefinition(
                nature_id="nature_test",
                nature_name="测试",
                positive_stat="speed",
                positive_multiplier=1.2,
                negative_stat="physical_attack",
                negative_multiplier=0.9,
                neutral_multiplier=1.0,
            ),
            PlayerElfBuild(
                build_id="build_alpha",
                build_name="甲配置",
                elf_id="elf_alpha",
                nature_id="nature_test",
                individual_talent_distribution_json=dumps_json({}),
                final_stats_json=dumps_json({}),
            ),
            PlayerElfBuild(
                build_id="build_beta",
                build_name="乙配置",
                elf_id="elf_beta",
                nature_id="nature_test",
                individual_talent_distribution_json=dumps_json({}),
                final_stats_json=dumps_json({}),
            ),
        ]
    )
    session.commit()
