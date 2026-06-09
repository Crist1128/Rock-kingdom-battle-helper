"""候选生成范围测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.calculation.stat_calculator import NatureRule
from app.core.enums import StatKey
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
    """候选生成支持分层收缩空间。"""
    generator = CandidateGenerator()

    assert generator.generate_candidate_count(mode=CandidateGenerationMode.FULL) == 46320
    assert generator.generate_candidate_count(mode=CandidateGenerationMode.BALANCED) == 3888
    assert generator.generate_candidate_count(mode=CandidateGenerationMode.WIDE) == 576
    assert generator.generate_candidate_count(mode=CandidateGenerationMode.STANDARD) == 188


def test_candidate_service_standard_mode_keeps_positive_stat_investment(
    db_session: Session,
) -> None:
    """standard 候选应符合主流极速空间规则。"""
    generated = CandidateService(db_session).generate_for_enemy_elf(
        "battle_candidate",
        "enemy_elf",
        mode=CandidateGenerationMode.STANDARD,
    )

    assert generated == 48
    rows = list(
        db_session.scalars(
            select(BuildCandidate).where(
                BuildCandidate.battle_id == "battle_candidate",
                BuildCandidate.elf_id == "enemy_elf",
                BuildCandidate.nature_id == "magic_attack_plus_physical_attack_minus",
            )
        )
    )
    assert len(rows) == 24
    for row in rows:
        distribution = loads_json(row.individual_talent_distribution_json, {})
        assert int(distribution["magic_attack"]) == 10
        assert int(distribution["physical_attack"]) == 0
        assert all(int(value) in {0, 9, 10} for value in distribution.values())
        assert sum(1 for value in distribution.values() if int(value) > 0) == 3


def test_candidate_service_wide_and_balanced_modes_expand_candidate_space(
    db_session: Session,
) -> None:
    """宽松模式保留更多候选，用于主流空间匹配失败后的兜底扩展。"""
    service = CandidateService(db_session)

    assert service.generate_for_enemy_elf(
        "battle_candidate",
        "enemy_elf",
        mode=CandidateGenerationMode.WIDE,
    ) == 48
    assert service.generate_for_enemy_elf(
        "battle_candidate",
        "enemy_elf",
        mode=CandidateGenerationMode.BALANCED,
    ) == 324


def test_candidate_generator_standard_mode_ignores_unpopular_negative_stats() -> None:
    """standard 不考虑负面减少生命、物防、魔防的性格。"""
    generator = CandidateGenerator()
    hp_negative = generator.generate_individual_talent_distributions_for_nature(
        NatureRule(
            nature_id="speed_plus_hp_minus",
            positive_stat=StatKey.SPEED,
            negative_stat=StatKey.HP,
        ),
        mode=CandidateGenerationMode.STANDARD,
    )
    physical_attack_negative = generator.generate_individual_talent_distributions_for_nature(
        NatureRule(
            nature_id="speed_plus_physical_attack_minus",
            positive_stat=StatKey.SPEED,
            negative_stat=StatKey.PHYSICAL_ATTACK,
        ),
        mode=CandidateGenerationMode.STANDARD,
    )

    assert hp_negative == []
    assert len(physical_attack_negative) == 24


def test_candidate_service_full_mode_still_available(db_session: Session) -> None:
    """full 模式保留完整候选空间，用于后台补全或手动重建。"""
    generated = CandidateService(db_session).generate_for_enemy_elf(
        "battle_candidate",
        "enemy_elf",
        mode=CandidateGenerationMode.FULL,
    )

    assert generated == 3088


def test_candidate_selection_options_only_use_active_candidates(db_session: Session) -> None:
    """候选选择面板只应提供未排除候选中的性格和资质组合。"""
    service = CandidateService(db_session)
    service.generate_for_enemy_elf(
        "battle_candidate",
        "enemy_elf",
        mode=CandidateGenerationMode.STANDARD,
    )
    for row in db_session.scalars(
        select(BuildCandidate).where(
            BuildCandidate.battle_id == "battle_candidate",
            BuildCandidate.elf_id == "enemy_elf",
            BuildCandidate.nature_id == "magic_attack_plus_physical_attack_minus",
        )
    ):
        row.is_excluded = True
        row.excluded_reason = "test_excluded"
    db_session.commit()

    options = service.get_selection_options("battle_candidate", "enemy_elf")

    nature_ids = {item.nature_id for item in options.nature_options}
    assert nature_ids == {"speed_plus_magic_attack_minus"}
    assert options.panel_candidate is not None
    assert options.panel_candidate.is_excluded is False
