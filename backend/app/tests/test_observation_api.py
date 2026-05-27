"""观察事件 API 测试。

第三里程碑要求确认：前端通过 HTTP 提交观察事件后，后端会真正调用推理引擎，
并把候选的匹配分数、置信度和证据链写回数据库。
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# 导入所有模型模块，确保 Base.metadata.create_all 能创建带外键的完整表结构。
from app.api.router import api_router
from app.db.base import Base
from app.db.session import get_db
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle
from app.models.candidate import BuildCandidate
from app.models.static import ElfDefinition, NatureDefinition, TypeEffectivenessRule
from app.utils.json import dumps_json, loads_json


@pytest.fixture()
def api_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    """创建隔离的测试 API 客户端与内存数据库。

    TestClient 会在另一个线程中处理请求，因此内存 SQLite 必须使用 StaticPool 与
    ``check_same_thread=False``，这样测试线程和请求线程看到的是同一个数据库连接。
    """
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
        _seed_base_data(session)

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
        yield TestClient(app), TestingSessionLocal
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_base_data(session: Session) -> None:
    """写入候选反推 API 测试所需的最小静态数据与战斗记录。"""
    session.add_all(
        [
            Battle(battle_id="battle_1", battle_name="observation api test"),
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


def _candidate(candidate_id: str, *, physical_defense: int) -> BuildCandidate:
    """构造一条候选配置，只填充本次 API 测试依赖的字段。"""
    return BuildCandidate(
        candidate_id=candidate_id,
        battle_id="battle_1",
        side="enemy",
        elf_id="enemy_elf",
        nature_id="nature_1",
        individual_talent_distribution_json=dumps_json({"physical_defense": physical_defense}),
        final_hp=300,
        final_physical_attack=100,
        final_physical_defense=physical_defense,
        final_magic_attack=100,
        final_magic_defense=100,
        final_speed=100,
        possible_skill_ids_json=dumps_json([]),
        confirmed_skill_ids_json=dumps_json([]),
        match_score=0.0,
        confidence=0.0,
        is_excluded=False,
    )


def test_process_damage_observation_updates_candidate_scores(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """提交伤害数字观察后，应按普通攻击公式更新候选评分与证据链。"""
    client, session_factory = api_client
    with session_factory() as session:
        session.add_all(
            [
                _candidate("candidate_low_defense", physical_defense=100),
                _candidate("candidate_high_defense", physical_defense=200),
            ]
        )
        session.commit()

    response = client.post(
        "/api/v1/observations/battle_1",
        json={
            "enemy_elf_id": "enemy_elf",
            "event_id": "event_damage_api_1",
            "observation_type": "damage_value",
            "observed_value": 90,
            "payload": {
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
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["battle_id"] == "battle_1"
    assert body["enemy_elf_id"] == "enemy_elf"
    assert body["event_id"] == "event_damage_api_1"
    assert body["observation_type"] == "damage_value"
    assert body["candidate_count"] == 2
    assert body["matched_count"] == 1
    assert body["mismatched_count"] == 1
    assert body["unknown_count"] == 0
    assert body["hard_excluded_count"] == 0
    assert body["hard_filter_applied"] is False
    assert body["top_candidate_id"] == "candidate_low_defense"
    assert body["top_confidence"] > 0.5

    with session_factory() as session:
        rows = {
            row.candidate_id: row
            for row in session.scalars(select(BuildCandidate)).all()
        }
    assert rows["candidate_low_defense"].match_score > rows["candidate_high_defense"].match_score
    assert rows["candidate_low_defense"].confidence > rows["candidate_high_defense"].confidence
    assert rows["candidate_high_defense"].is_excluded is False

    evidence = loads_json(rows["candidate_low_defense"].evidence_ids_json, [])
    assert evidence[0]["event_id"] == "event_damage_api_1"
    assert evidence[0]["reason"] == "damage_value_matched"
    assert evidence[0]["predicted_value"] == 90


def test_process_observation_returns_404_for_missing_battle(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """战斗不存在时，接口应返回 404，避免误写候选证据链。"""
    client, _session_factory = api_client

    response = client.post(
        "/api/v1/observations/missing_battle",
        json={
            "enemy_elf_id": "enemy_elf",
            "observation_type": "skill_seen",
            "payload": {"skill_id": "skill_a"},
        },
    )

    assert response.status_code == 404


def test_process_damage_observation_can_resolve_basic_rules(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """?? resolve_rules ??API ????????????????????"""
    client, session_factory = api_client
    with session_factory() as session:
        session.add_all(
            [
                TypeEffectivenessRule(
                    attack_element_type="fire",
                    defense_element_type="grass",
                    multiplier=2.0,
                ),
                _candidate("candidate_low_defense_rule", physical_defense=100),
                _candidate("candidate_high_defense_rule", physical_defense=200),
            ]
        )
        session.commit()

    response = client.post(
        "/api/v1/observations/battle_1",
        json={
            "enemy_elf_id": "enemy_elf",
            "event_id": "event_damage_rule_api_1",
            "observation_type": "damage_value",
            "observed_value": 225,
            "payload": {
                "resolve_rules": True,
                "attacker_panel_stats": {
                    "hp": 300,
                    "physical_attack": 200,
                    "physical_defense": 100,
                    "magic_attack": 100,
                    "magic_defense": 100,
                    "speed": 100,
                },
                "skill_category": "physical",
                "skill_element_type": "fire",
                "attacker_element_types": ["fire"],
                "defender_element_types": ["grass"],
                "base_power": 50,
                "damage_tolerance": 0,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched_count"] == 1
    assert body["mismatched_count"] == 1
    assert body["unknown_count"] == 0
    assert body["top_candidate_id"] == "candidate_low_defense_rule"

    with session_factory() as session:
        rows = {
            row.candidate_id: row
            for row in session.scalars(select(BuildCandidate)).all()
        }
    evidence = loads_json(rows["candidate_low_defense_rule"].evidence_ids_json, [])
    details = evidence[0]["details"]
    assert Decimal(details["display_power"]) == Decimal("125")
    assert details["rule_resolution_enabled"] is True
    assert details["rule_resolution_details"]["type_multiplier"]["value"] == "2.0"
