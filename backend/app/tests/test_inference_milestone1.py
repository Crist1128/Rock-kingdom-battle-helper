"""Milestone 1 候选反推骨架测试。

这些测试覆盖第一阶段的核心闭环：
玩家观测 -> matcher 判断 -> InferenceEngine 更新候选软评分和置信度。
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# 导入相关模型模块，确保 Base.metadata 收集到外键引用表。
from app.db.base import Base
from app.inference.inference_engine import InferenceEngine
from app.inference.observation_matcher import ObservationEventInput
from app.inference.observation_types import ObservationType
from app.inference.skill_pool_matcher import SkillPoolMatcher
from app.inference.speed_matcher import SpeedMatcher
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle
from app.models.candidate import BuildCandidate
from app.models.static import ElfDefinition, NatureDefinition
from app.utils.json import dumps_json, loads_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建独立内存数据库，避免污染开发数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    session.add_all(
        [
            Battle(battle_id="battle_1", battle_name="test battle"),
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
                nature_id="nature_1",
                nature_name="测试性格",
                positive_stat="physical_attack",
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


def _candidate(
    candidate_id: str,
    *,
    hp: int = 300,
    physical_defense: int = 100,
    speed: int = 100,
    possible_skill_ids: list[str] | None = None,
) -> BuildCandidate:
    """构造测试候选，只填充反推骨架需要的字段。"""
    return BuildCandidate(
        candidate_id=candidate_id,
        battle_id="battle_1",
        side="enemy",
        elf_id="enemy_elf",
        nature_id="nature_1",
        individual_talent_distribution_json=dumps_json({"speed": 10}),
        final_hp=hp,
        final_physical_attack=100,
        final_physical_defense=physical_defense,
        final_magic_attack=100,
        final_magic_defense=100,
        final_speed=speed,
        possible_skill_ids_json=(
            dumps_json(possible_skill_ids) if possible_skill_ids is not None else None
        ),
        confirmed_skill_ids_json=dumps_json([]),
        match_score=0.0,
        confidence=0.0,
        is_excluded=False,
    )


def test_skill_pool_matcher_respects_reliability() -> None:
    """技能池可靠时可扣分；技能池不可靠时只返回 unknown。"""
    matcher = SkillPoolMatcher()

    matched = matcher.match_skill_seen(
        skill_id="skill_a",
        possible_skill_ids=["skill_a", "skill_b"],
        skill_pool_reliable=True,
    )
    assert matched.matched is True
    assert matched.score_delta > 0

    mismatched = matcher.match_skill_seen(
        skill_id="skill_x",
        possible_skill_ids=["skill_a", "skill_b"],
        skill_pool_reliable=True,
    )
    assert mismatched.matched is False
    assert mismatched.can_hard_exclude is True

    unknown = matcher.match_skill_seen(
        skill_id="skill_x",
        possible_skill_ids=["skill_a", "skill_b"],
        skill_pool_reliable=False,
    )
    assert unknown.matched is None
    assert "skill_pool_unreliable" in unknown.unknown_factors


def test_speed_matcher_uses_panel_speed_only_when_no_unknown_factors() -> None:
    """基础速度匹配只在没有优先级/状态等未知因素时生效。"""
    matcher = SpeedMatcher()

    matched = matcher.match_speed_order(
        observed_order="self_first",
        self_speed=120,
        candidate_speed=100,
    )
    assert matched.matched is True
    assert matched.predicted_value == "self_first"

    mismatched = matcher.match_speed_order(
        observed_order="enemy_first",
        self_speed=120,
        candidate_speed=100,
    )
    assert mismatched.matched is False
    assert mismatched.can_hard_exclude is True

    unknown = matcher.match_speed_order(
        observed_order="self_first",
        self_speed=120,
        candidate_speed=100,
        unknown_factors=["priority_modifier_unknown"],
    )
    assert unknown.matched is None
    assert "priority_modifier_unknown" in unknown.unknown_factors


def test_inference_engine_updates_skill_seen_soft_scores(db_session: Session) -> None:
    """技能出现观测应更新候选分数、证据链和置信度，但默认不硬排除。"""
    db_session.add_all(
        [
            _candidate("candidate_match", possible_skill_ids=["skill_a", "skill_b"]),
            _candidate("candidate_mismatch", possible_skill_ids=["skill_c"]),
            _candidate("candidate_unknown", possible_skill_ids=None),
        ]
    )
    db_session.commit()

    engine = InferenceEngine(db_session)
    summary = engine.process_observation_event(
        ObservationEventInput(
            battle_id="battle_1",
            enemy_elf_id="enemy_elf",
            event_id="event_skill_seen_1",
            observation_type=ObservationType.SKILL_SEEN,
            payload={"skill_id": "skill_a", "skill_pool_reliable": True},
        )
    )

    rows = {row.candidate_id: row for row in db_session.query(BuildCandidate).all()}
    assert summary["candidate_count"] == 3
    assert summary["matched_count"] == 1
    assert summary["mismatched_count"] == 1
    assert summary["unknown_count"] == 1
    assert summary["hard_excluded_count"] == 0

    assert rows["candidate_match"].match_score > rows["candidate_unknown"].match_score
    assert rows["candidate_unknown"].match_score > rows["candidate_mismatch"].match_score
    assert rows["candidate_match"].confidence > rows["candidate_unknown"].confidence
    assert rows["candidate_unknown"].confidence > rows["candidate_mismatch"].confidence
    assert rows["candidate_mismatch"].is_excluded is False

    matched_events = loads_json(rows["candidate_match"].matched_event_ids_json, [])
    mismatched_events = loads_json(rows["candidate_mismatch"].mismatched_event_ids_json, [])
    evidence = loads_json(rows["candidate_match"].evidence_ids_json, [])
    assert matched_events == ["event_skill_seen_1"]
    assert mismatched_events == ["event_skill_seen_1"]
    assert evidence[0]["observation_type"] == "skill_seen"


def test_inference_engine_updates_speed_order_soft_scores(db_session: Session) -> None:
    """速度先后手观测应基于候选速度更新分数。"""
    db_session.add_all(
        [
            _candidate("candidate_slow", speed=80, possible_skill_ids=[]),
            _candidate("candidate_fast", speed=120, possible_skill_ids=[]),
        ]
    )
    db_session.commit()

    engine = InferenceEngine(db_session)
    summary = engine.process_observation_event(
        ObservationEventInput(
            battle_id="battle_1",
            enemy_elf_id="enemy_elf",
            event_id="event_speed_1",
            observation_type=ObservationType.SPEED_ORDER,
            observed_value="self_first",
            payload={"self_speed": 100},
        )
    )

    rows = {row.candidate_id: row for row in db_session.query(BuildCandidate).all()}
    assert summary["matched_count"] == 1
    assert summary["mismatched_count"] == 1
    assert rows["candidate_slow"].match_score > rows["candidate_fast"].match_score
    assert rows["candidate_slow"].confidence > rows["candidate_fast"].confidence
    assert rows["candidate_fast"].is_excluded is False



def test_inference_engine_updates_damage_value_soft_scores(db_session: Session) -> None:
    """整数伤害观测应通过普通伤害公式反推候选防御。"""
    db_session.add_all(
        [
            _candidate("candidate_low_defense", physical_defense=100),
            _candidate("candidate_high_defense", physical_defense=200),
        ]
    )
    db_session.commit()

    engine = InferenceEngine(db_session)
    summary = engine.process_observation_event(
        ObservationEventInput(
            battle_id="battle_1",
            enemy_elf_id="enemy_elf",
            event_id="event_damage_1",
            observation_type=ObservationType.DAMAGE_VALUE,
            observed_value=90,
            payload={
                "attacker_panel_stats": {
                    "hp": 300,
                    "physical_attack": 200,
                    "physical_defense": 100,
                    "magic_attack": 100,
                    "magic_defense": 100,
                    "speed": 100,
                },
                "skill_category": "physical",
                "base_power": 50,
                "damage_tolerance": 0,
            },
        )
    )

    rows = {row.candidate_id: row for row in db_session.query(BuildCandidate).all()}
    assert summary["matched_count"] == 1
    assert summary["mismatched_count"] == 1
    assert rows["candidate_low_defense"].match_score > rows["candidate_high_defense"].match_score
    assert rows["candidate_low_defense"].confidence > rows["candidate_high_defense"].confidence
    assert rows["candidate_high_defense"].is_excluded is False

    evidence = loads_json(rows["candidate_low_defense"].evidence_ids_json, [])
    assert evidence[0]["reason"] == "damage_value_matched"
    assert evidence[0]["predicted_value"] == 90


def test_inference_engine_updates_hp_percent_delta_soft_scores(db_session: Session) -> None:
    """扣血百分比观测应同时受理论伤害与候选最大 HP 影响。"""
    db_session.add_all(
        [
            _candidate("candidate_300_hp", hp=300, physical_defense=100),
            _candidate("candidate_600_hp", hp=600, physical_defense=100),
        ]
    )
    db_session.commit()

    engine = InferenceEngine(db_session)
    summary = engine.process_observation_event(
        ObservationEventInput(
            battle_id="battle_1",
            enemy_elf_id="enemy_elf",
            event_id="event_pct_1",
            observation_type=ObservationType.HP_PERCENT_DELTA,
            observed_value=30.0,
            payload={
                "attacker_panel_stats": {
                    "hp": 300,
                    "physical_attack": 200,
                    "physical_defense": 100,
                    "magic_attack": 100,
                    "magic_defense": 100,
                    "speed": 100,
                },
                "skill_category": "physical",
                "base_power": 50,
                "percent_tolerance": 0.1,
            },
        )
    )

    rows = {row.candidate_id: row for row in db_session.query(BuildCandidate).all()}
    assert summary["matched_count"] == 1
    assert summary["mismatched_count"] == 1
    assert rows["candidate_300_hp"].match_score > rows["candidate_600_hp"].match_score
    assert rows["candidate_300_hp"].confidence > rows["candidate_600_hp"].confidence
