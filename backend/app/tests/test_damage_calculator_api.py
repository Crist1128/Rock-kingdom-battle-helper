"""独立伤害计算器 API 测试。"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.db.base import Base
from app.db.session import get_db
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import estimate as _estimate_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState, BattleSkillSlot
from app.models.event import BattleEvent, DamageEvent
from app.models.static import ElfDefinition, NatureDefinition, SkillDefinition
from app.utils.json import dumps_json


@pytest.fixture()
def api_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    """创建隔离数据库和测试客户端。"""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    Base.metadata.create_all(engine)

    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    def override_get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def seed_static_data(session: Session) -> None:
    """写入最小静态数据。"""
    session.add_all(
        [
            ElfDefinition(
                elf_id="elf_attacker",
                elf_name="攻击测试精灵",
                avatar="attacker.png",
                element_types_json=dumps_json(["fire"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=80,
                base_magic_attack_talent=70,
                base_magic_defense_talent=80,
                base_speed_talent=90,
            ),
            ElfDefinition(
                elf_id="elf_defender",
                elf_name="防御测试精灵",
                avatar="defender.png",
                element_types_json=dumps_json(["grass"]),
                base_hp_talent=100,
                base_physical_attack_talent=70,
                base_physical_defense_talent=100,
                base_magic_attack_talent=70,
                base_magic_defense_talent=100,
                base_speed_talent=80,
            ),
            NatureDefinition(
                nature_id="nature_attack",
                nature_name="物攻性格",
                positive_stat="physical_attack",
                negative_stat="magic_attack",
                positive_multiplier=1.2,
                negative_multiplier=0.9,
                neutral_multiplier=1.0,
            ),
            NatureDefinition(
                nature_id="nature_defense",
                nature_name="物防性格",
                positive_stat="physical_defense",
                negative_stat="magic_attack",
                positive_multiplier=1.2,
                negative_multiplier=0.9,
                neutral_multiplier=1.0,
            ),
            SkillDefinition(
                skill_id="skill_test",
                skill_name="测试打击",
                element_type="fire",
                skill_category="physical",
                base_power=50,
                base_energy_cost=2,
                priority_modifier=0,
            ),
        ]
    )
    session.commit()


def test_bootstrap_returns_null_when_no_battle(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_client

    response = client.get("/api/v1/damage-calculator/bootstrap")

    assert response.status_code == 200
    assert response.json() == {"latest_battle": None, "type_effectiveness_rules": []}


def test_calculate_basic_attack_without_writing_battle_events(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        seed_static_data(session)

    response = client.post(
        "/api/v1/damage-calculator/calculate",
        json={
            "attacker": {
                "elf_id": "elf_attacker",
                "nature_id": "nature_attack",
                "individual_talent_distribution": {"hp": 10, "physical_attack": 10},
            },
            "defender": {
                "elf_id": "elf_defender",
                "nature_id": "nature_defense",
                "individual_talent_distribution": {"hp": 10, "physical_defense": 10},
            },
            "skill_id": "skill_test",
            "modifiers": {"hit_count": 2, "weather_multiplier": 1.5},
            "observed_damage_value": 120,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "calculated"
    assert body["damage_value"] is not None
    assert body["damage_percent"] is not None
    assert body["attacker"]["panel_source"] == "calculated_from_elf_nature_talents"
    assert body["defender"]["panel_source"] == "calculated_from_elf_nature_talents"
    assert body["observed_comparison"]["inference_status"] == "reserved"
    assert body["side_effect_policy"] == "read_only_no_battle_mutation"

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BattleEvent)) == 0
        assert session.scalar(select(func.count()).select_from(DamageEvent)) == 0


def test_bootstrap_reads_latest_battle_lineup(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        seed_static_data(session)
        session.add(
            Battle(
                battle_id="battle_latest",
                battle_name="最近战斗",
                phase="battle",
                turn_number=2,
                self_active_elf_id="elf_attacker",
                enemy_active_elf_id="elf_defender",
            )
        )
        session.add_all(
            [
                BattleElfState(
                    state_id="state_self",
                    battle_id="battle_latest",
                    side="self",
                    elf_id="elf_attacker",
                    elf_name="攻击测试精灵",
                    avatar="attacker.png",
                    nature_id="nature_attack",
                    individual_talent_distribution_json=dumps_json({"hp": 10}),
                    panel_stats_json=dumps_json(
                        {
                            "hp": 300,
                            "physical_attack": 200,
                            "physical_defense": 100,
                            "magic_attack": 100,
                            "magic_defense": 100,
                            "speed": 100,
                        }
                    ),
                    current_hp_percent=100,
                    is_active_elf=True,
                ),
                BattleElfState(
                    state_id="state_enemy",
                    battle_id="battle_latest",
                    side="enemy",
                    elf_id="elf_defender",
                    elf_name="防御测试精灵",
                    avatar="defender.png",
                    panel_stats_json=dumps_json(
                        {
                            "hp": 320,
                            "physical_attack": 100,
                            "physical_defense": 150,
                            "magic_attack": 100,
                            "magic_defense": 150,
                            "speed": 90,
                        }
                    ),
                    current_hp_percent=88,
                    is_active_elf=True,
                ),
                BattleSkillSlot(
                    slot_id="slot_1",
                    battle_id="battle_latest",
                    side="self",
                    elf_id="elf_attacker",
                    slot_index=0,
                    skill_id="skill_test",
                ),
            ]
        )
        session.commit()

    response = client.get("/api/v1/damage-calculator/bootstrap")

    assert response.status_code == 200
    latest = response.json()["latest_battle"]
    assert latest["battle_id"] == "battle_latest"
    assert latest["self_lineup"][0]["elf_id"] == "elf_attacker"
    assert latest["self_lineup"][0]["skill_ids"] == ["skill_test"]
    assert latest["enemy_lineup"][0]["panel_stats"]["hp"] == 320


def test_infer_defender_returns_soft_candidates_without_writing_estimates(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        seed_static_data(session)

    response = client.post(
        "/api/v1/damage-calculator/infer-defender",
        json={
            "attacker": {
                "elf_id": "elf_attacker",
                "nature_id": "nature_attack",
                "individual_talent_distribution": {"hp": 10, "physical_attack": 10},
            },
            "defender_elf_id": "elf_defender",
            "skill_id": "skill_test",
            "modifiers": {"hit_count": 1},
            "observed_damage_value": 80,
            "top_n": 5,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ranked"
    assert body["searched_candidate_count"] == 242
    assert body["returned_candidate_count"] == 5
    assert body["candidates"][0]["rank"] == 1
    assert body["candidates"][0]["relevant_defense_stat"] == "physical_defense"
    assert body["side_effect_policy"] == "read_only_no_battle_mutation"

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BattleEvent)) == 0
        assert session.scalar(select(func.count()).select_from(DamageEvent)) == 0


def test_infer_defender_batch_accumulates_sample_deltas(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        seed_static_data(session)

    response = client.post(
        "/api/v1/damage-calculator/infer-defender-batch",
        json={
            "defender_elf_id": "elf_defender",
            "candidate_mode": "focused",
            "tolerance": 2,
            "top_n": 3,
            "samples": [
                {
                    "label": "第一段",
                    "attacker": {
                        "elf_id": "elf_attacker",
                        "nature_id": "nature_attack",
                        "individual_talent_distribution": {"hp": 10, "physical_attack": 10},
                    },
                    "skill_id": "skill_test",
                    "modifiers": {"hit_count": 1},
                    "observed_damage_value": 80,
                },
                {
                    "label": "天气段",
                    "attacker": {
                        "elf_id": "elf_attacker",
                        "nature_id": "nature_attack",
                        "individual_talent_distribution": {"hp": 10, "physical_attack": 10},
                    },
                    "skill_id": "skill_test",
                    "modifiers": {"hit_count": 1, "weather_multiplier": 1.5},
                    "observed_damage_value": 120,
                },
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ranked"
    assert body["searched_candidate_count"] == 242
    assert body["returned_candidate_count"] == 3
    assert body["tolerance"] == 2
    assert body["candidate_mode"] == "focused"
    first = body["candidates"][0]
    assert first["rank"] == 1
    assert first["sample_count"] == 2
    assert len(first["sample_results"]) == 2
    assert "total_absolute_delta" in first
