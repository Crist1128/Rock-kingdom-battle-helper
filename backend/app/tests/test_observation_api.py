"""观察事件 API 测试。"""

from collections.abc import Iterator

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
from app.models import estimate as _estimate_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState
from app.models.candidate import BuildCandidate
from app.models.estimate import EnemyPanelEstimate, EnemyPanelEstimateEvidence
from app.models.static import ElfDefinition, NatureDefinition
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
    session.flush()
    session.add(
        BattleElfState(
            state_id="state_enemy_elf",
            battle_id="battle_1",
            side="enemy",
            elf_id="enemy_elf",
            elf_name="测试敌方精灵",
            avatar="",
            panel_stats_json=dumps_json({}),
            current_hp_value=None,
            current_hp_percent=100.0,
            energy=10,
            skill_ids_json=dumps_json([]),
            confirmed_skill_ids_json=dumps_json([]),
            active_effect_instance_ids_json=dumps_json([]),
            is_active_elf=True,
            is_defeated=False,
            manual_override=True,
        )
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


def test_process_damage_observation_updates_estimate_constraints(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """提交伤害数字观察后，应更新实时估计约束，不再写旧候选评分。"""
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
    assert body["status"] == "estimate_updated"
    assert body["battle_id"] == "battle_1"
    assert body["enemy_elf_id"] == "enemy_elf"
    assert body["event_id"] == "event_damage_api_1"
    assert body["observation_type"] == "damage_value"
    assert body["inferred_stat_count"] >= 1
    assert "physical_defense" in body["affected_stats"]
    assert body["hard_filter_applied"] is False

    with session_factory() as session:
        rows = {
            row.candidate_id: row
            for row in session.scalars(select(BuildCandidate)).all()
        }
    assert rows["candidate_low_defense"].match_score == 0
    assert rows["candidate_high_defense"].match_score == 0
    assert rows["candidate_low_defense"].confidence == 0
    assert rows["candidate_high_defense"].confidence == 0
    assert rows["candidate_high_defense"].is_excluded is False
    assert rows["candidate_low_defense"].evidence_ids_json is None

    with session_factory() as session:
        estimate = session.scalar(
            select(EnemyPanelEstimate).where(
                EnemyPanelEstimate.battle_id == "battle_1",
                EnemyPanelEstimate.elf_id == "enemy_elf",
            )
        )
        estimate_evidence = session.scalar(
            select(EnemyPanelEstimateEvidence).where(
                EnemyPanelEstimateEvidence.source_event_id == "event_damage_api_1"
            )
        )
    assert estimate is not None
    assert estimate_evidence is not None
    assert estimate_evidence.observation_type == "damage_value"
    stat_constraints = loads_json(estimate.stat_constraints_json, {})
    assert stat_constraints["physical_defense"]["status"] == "formula_constraint_derived"
    assert stat_constraints["physical_defense"]["integer_min"] == 100
    assert stat_constraints["physical_defense"]["integer_max"] == 100

    estimate_evidence_response = client.get("/api/v1/estimates/battle_1/enemy_elf/evidence")
    assert estimate_evidence_response.status_code == 200
    estimate_evidence_body = estimate_evidence_response.json()
    assert estimate_evidence_body[0]["source_event_id"] == "event_damage_api_1"
    assert estimate_evidence_body[0]["constraint_delta"]["status"] == "formula_constraint_derived"
    assert estimate_evidence_body[0]["inferred_stats"]["physical_defense"]["integer_min"] == 100
    assert estimate_evidence_body[0]["inferred_stats"]["physical_defense"]["integer_max"] == 100


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
    """观察接口使用已解析的公式上下文更新实时估计。"""
    client, session_factory = api_client
    with session_factory() as session:
        session.add_all(
            [
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
                "type_multiplier": 2,
                "stab_multiplier": 1.25,
                "damage_tolerance": 0,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "estimate_updated"
    assert "physical_defense" in body["affected_stats"]

    with session_factory() as session:
        estimate = session.scalar(
            select(EnemyPanelEstimate).where(
                EnemyPanelEstimate.battle_id == "battle_1",
                EnemyPanelEstimate.elf_id == "enemy_elf",
            )
        )
    assert estimate is not None
    constraints = loads_json(estimate.stat_constraints_json, {})
    assert constraints["physical_defense"]["status"] == "formula_constraint_derived"


def test_process_damage_observation_accepts_v1_payload(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """v1 嵌套 Observation payload 应被归一化后进入实时估计。"""
    client, session_factory = api_client
    with session_factory() as session:
        session.add_all(
            [
                _candidate("candidate_v1_low_defense", physical_defense=100),
                _candidate("candidate_v1_high_defense", physical_defense=200),
            ]
        )
        session.commit()

    response = client.post(
        "/api/v1/observations/battle_1",
        json={
            "enemy_elf_id": "enemy_elf",
            "event_id": "event_damage_v1_api_1",
            "observation_type": "damage_value",
            "observed_value": 90,
            "payload": {
                "schema_version": "observation_payload_v1",
                "context_kind": "damage",
                "roles": {"enemy_role": "defender"},
                "panels": {
                    "attacker": {
                        "hp": 300,
                        "physical_attack": 200,
                        "physical_defense": 100,
                        "magic_attack": 100,
                        "magic_defense": 100,
                        "speed": 100,
                    }
                },
                "skill": {"skill_category": "physical"},
                "formula": {"formula_type": "attack", "base_power": 50},
                "observed": {"damage_value": 90},
                "matching": {"damage_tolerance": 0},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "estimate_updated"
    assert "physical_defense" in body["affected_stats"]
    with session_factory() as session:
        estimate = session.scalar(
            select(EnemyPanelEstimate).where(
                EnemyPanelEstimate.battle_id == "battle_1",
                EnemyPanelEstimate.elf_id == "enemy_elf",
            )
        )
    assert estimate is not None
    constraints = loads_json(estimate.stat_constraints_json, {})
    assert constraints["physical_defense"]["integer_min"] == 100
    assert constraints["physical_defense"]["integer_max"] == 100
