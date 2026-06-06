"""候选生成范围测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle
from app.models.candidate import BuildCandidate
from app.models.static import ElfDefinition, NatureDefinition
from app.services.candidate_service import (
    CandidateGenerationMode,
    CandidateGenerator,
    CandidateService,
)
from app.utils.json import dumps_json, loads_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建独立内存数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    session.add_all(
        [
            Battle(battle_id="battle_candidate", battle_name="candidate test"),
            ElfDefinition(
                elf_id="enemy_elf",
                elf_name="测试敌方精灵",
                avatar="",
                element_types_json=dumps_json(["normal"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
            NatureDefinition(
                nature_id="magic_attack_plus_physical_attack_minus",
                nature_name="加魔攻减物攻",
                positive_stat="magic_attack",
                negative_stat="physical_attack",
            ),
            NatureDefinition(
                nature_id="speed_plus_magic_attack_minus",
                nature_name="加速度减魔攻",
                positive_stat="speed",
                negative_stat="magic_attack",
            ),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_candidate_generator_standard_mode_reduces_candidate_count() -> None:
    """standard 模式只保留 8 及以上资质的常规组合。"""
    generator = CandidateGenerator()

    assert generator.generate_candidate_count(mode=CandidateGenerationMode.FULL) == 46320
    assert generator.generate_candidate_count(mode=CandidateGenerationMode.STANDARD) == 6030


def test_candidate_service_standard_mode_keeps_positive_stat_investment(
    db_session: Session,
) -> None:
    """加魔攻性格的 standard 候选应带 8 及以上魔攻资质，并默认不点负面物攻。"""
    generated = CandidateService(db_session).generate_for_enemy_elf(
        "battle_candidate",
        "enemy_elf",
        mode=CandidateGenerationMode.STANDARD,
    )

    assert generated == 402
    rows = list(
        db_session.scalars(
            select(BuildCandidate).where(
                BuildCandidate.battle_id == "battle_candidate",
                BuildCandidate.elf_id == "enemy_elf",
                BuildCandidate.nature_id == "magic_attack_plus_physical_attack_minus",
            )
        )
    )
    assert len(rows) == 201
    for row in rows:
        distribution = loads_json(row.individual_talent_distribution_json, {})
        assert int(distribution["magic_attack"]) >= 8
        assert int(distribution["physical_attack"]) == 0
        assert all(int(value) in {0, 8, 9, 10} for value in distribution.values())


def test_candidate_service_full_mode_still_available(db_session: Session) -> None:
    """full 模式保留完整候选空间，用于后台补全或手动重建。"""
    generated = CandidateService(db_session).generate_for_enemy_elf(
        "battle_candidate",
        "enemy_elf",
        mode=CandidateGenerationMode.FULL,
    )

    assert generated == 3088
