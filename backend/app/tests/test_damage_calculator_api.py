"""独立伤害计算器 API 测试。"""

from collections.abc import Iterator
from decimal import Decimal

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
from app.schemas.damage_calculator import (
    DamageCalculatorAttackerCandidateOut,
    DamageCalculatorDefenderCandidateOut,
    DamageCalculatorPanelOut,
    DamageCalculatorTalentInput,
)
from app.services.standalone_damage_service import StandaloneDamageService
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
            NatureDefinition(
                nature_id="nature_hp",
                nature_name="生命+物攻-",
                positive_stat="hp",
                negative_stat="physical_attack",
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


def test_calculate_accepts_manual_base_power_override(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        seed_static_data(session)

    base_payload = {
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
        "modifiers": {"hit_count": 1},
    }
    normal = client.post("/api/v1/damage-calculator/calculate", json=base_payload)
    overridden = client.post(
        "/api/v1/damage-calculator/calculate",
        json={**base_payload, "modifiers": {"hit_count": 1, "base_power_override": 100}},
    )

    assert normal.status_code == 200, normal.text
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["damage_value"] > normal.json()["damage_value"]


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
            "observed_damage_value": 68,
            "observed_hp_percent_before": 100,
            "observed_hp_percent_after": 80,
            "top_n": 5,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ranked"
    assert body["searched_candidate_count"] == 60
    assert body["returned_candidate_count"] >= 1
    assert body["observed_hp_percent_delta"] == 20
    assert body["candidates"][0]["rank"] == 1
    assert body["candidates"][0]["relevant_defense_stat"] == "physical_defense"
    assert body["candidates"][0]["predicted_damage_percent"] is not None
    assert body["candidates"][0]["delta_damage_percent"] is not None
    assert sum(
        1
        for value in body["candidates"][0]["individual_talent_distribution"].values()
        if value > 0
    ) == 3
    assert body["side_effect_policy"] == "read_only_no_battle_mutation"

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BattleEvent)) == 0
        assert session.scalar(select(func.count()).select_from(DamageEvent)) == 0


def test_infer_defender_can_also_use_exact_damage_as_secondary_signal(
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
            "observed_damage_value": 68,
            "observed_hp_percent_before": 100,
            "observed_hp_percent_after": 80,
            "top_n": 3,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ranked"
    assert body["searched_candidate_count"] == 60
    assert body["returned_candidate_count"] >= 1
    first = body["candidates"][0]
    assert first["rank"] == 1
    assert "combined_error" in first
    assert first["absolute_delta"] == 0
    assert first["absolute_delta_damage_percent"] is not None
    assert all(candidate["absolute_delta"] == 0 for candidate in body["candidates"])
    assert all(candidate["matched_within_tolerance"] for candidate in body["candidates"])


def test_infer_attacker_returns_candidates_for_known_defender_damage(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """已知防御方面板和真实伤害时，可以反推攻击方性格/资质候选。"""
    client, session_factory = api_client
    with session_factory() as session:
        seed_static_data(session)

    calculate_response = client.post(
        "/api/v1/damage-calculator/calculate",
        json={
            "attacker": {
                "elf_id": "elf_attacker",
                "nature_id": "nature_attack",
                "individual_talent_distribution": {
                    "hp": 10,
                    "physical_attack": 10,
                    "speed": 10,
                },
            },
            "defender": {
                "elf_id": "elf_defender",
                "nature_id": "nature_defense",
                "individual_talent_distribution": {"hp": 10, "physical_defense": 10},
            },
            "skill_id": "skill_test",
            "modifiers": {"hit_count": 1},
        },
    )
    assert calculate_response.status_code == 200, calculate_response.text
    observed_damage = calculate_response.json()["damage_value"]

    response = client.post(
        "/api/v1/damage-calculator/infer-attacker",
        json={
            "attacker_elf_id": "elf_attacker",
            "defender": {
                "elf_id": "elf_defender",
                "nature_id": "nature_defense",
                "individual_talent_distribution": {"hp": 10, "physical_defense": 10},
            },
            "skill_id": "skill_test",
            "modifiers": {"hit_count": 1},
            "observed_damage_value": observed_damage,
            "top_n": 20,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ranked"
    assert body["relevant_attack_stat"] == "physical_attack"
    assert body["searched_candidate_count"] == 60
    assert body["returned_candidate_count"] >= 1
    assert all(
        candidate["predicted_damage_value"] == observed_damage
        for candidate in body["candidates"]
    )
    assert any(
        candidate["is_relevant_attack_positive_nature"]
        and candidate["has_relevant_attack_talent"]
        for candidate in body["candidates"]
    )


def test_infer_attacker_keeps_speed_positive_group_when_truncated() -> None:
    """攻击方反推命中候选较多时，也不能让加速性格被 top_n 截断得像被排除。"""
    natures = [
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
            nature_id="nature_speed",
            nature_name="速度性格",
            positive_stat="speed",
            negative_stat="magic_attack",
            positive_multiplier=1.2,
            negative_multiplier=0.9,
            neutral_multiplier=1.0,
        ),
    ]
    candidates = [
        _attacker_candidate_for_sort("nature_attack", "物攻性格", "生命+物攻+速度"),
        _attacker_candidate_for_sort("nature_attack", "物攻性格", "生命+物攻+物防"),
        _attacker_candidate_for_sort("nature_speed", "速度性格", "生命+物攻+速度"),
    ]

    selected = StandaloneDamageService._diversify_attacker_candidates_by_positive_stat(
        candidates,
        natures=natures,
        top_n=2,
    )

    assert {candidate.nature_id for candidate in selected} == {"nature_attack", "nature_speed"}


def test_infer_defender_keeps_diverse_positive_nature_groups(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """命中候选较多时，返回结果要覆盖不同正面性格，避免误看成被排除。"""
    client, session_factory = api_client
    with session_factory() as session:
        seed_static_data(session)
        session.add(
            NatureDefinition(
                nature_id="nature_magic_attack",
                nature_name="魔攻性格",
                positive_stat="magic_attack",
                negative_stat="physical_attack",
                positive_multiplier=1.2,
                negative_multiplier=0.9,
                neutral_multiplier=1.0,
            )
        )
        session.commit()

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
            "observed_damage_value": 65,
            "observed_hp_percent_before": 100,
            "observed_hp_percent_after": 84,
            "top_n": 4,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    returned_nature_ids = {candidate["nature_id"] for candidate in body["candidates"]}
    assert "nature_magic_attack" in returned_nature_ids
    assert len(returned_nature_ids) > 1


def test_infer_defender_default_config_preference_prioritizes_documented_setup() -> None:
    """同误差候选排序时，优先展示默认配置文档推荐的性格与三维资质。"""
    nature_by_id = {
        "nature_attack": NatureDefinition(
            nature_id="nature_attack",
            nature_name="物攻性格",
            positive_stat="physical_attack",
            negative_stat="magic_attack",
            positive_multiplier=1.2,
            negative_multiplier=0.9,
            neutral_multiplier=1.0,
        ),
        "nature_hp": NatureDefinition(
            nature_id="nature_hp",
            nature_name="生命+物攻-",
            positive_stat="hp",
            negative_stat="physical_attack",
            positive_multiplier=1.2,
            negative_multiplier=0.9,
            neutral_multiplier=1.0,
        ),
    }
    default_rule = {
        "positive_stat": "physical_attack",
        "negative_stat": "magic_attack",
        "talents": {
            "hp": 10,
            "physical_attack": 10,
            "physical_defense": 10,
            "magic_attack": 0,
            "magic_defense": 0,
            "speed": 0,
        },
    }
    preferred = _candidate_for_sort(
        nature_id="nature_attack",
        nature_name="物攻性格",
        talents=DamageCalculatorTalentInput(
            hp=10,
            physical_attack=10,
            physical_defense=10,
        ),
    )
    fallback = _candidate_for_sort(
        nature_id="nature_hp",
        nature_name="生命+物攻-",
        talents=DamageCalculatorTalentInput(
            hp=10,
            physical_defense=10,
            magic_defense=10,
        ),
    )

    assert StandaloneDamageService._default_config_preference(
        preferred,
        default_rule,
        nature_by_id,
    ) < StandaloneDamageService._default_config_preference(
        fallback,
        default_rule,
        nature_by_id,
    )


def test_positive_nature_talent_preference_requires_speed_for_speed_nature() -> None:
    """速度+ 性格的同误差候选应优先展示包含速度资质的三维配置。"""
    nature_by_id = {
        "nature_speed": NatureDefinition(
            nature_id="nature_speed",
            nature_name="速度性格",
            positive_stat="speed",
            negative_stat="magic_attack",
            positive_multiplier=1.2,
            negative_multiplier=0.9,
            neutral_multiplier=1.0,
        )
    }
    with_speed = _candidate_for_sort(
        nature_id="nature_speed",
        nature_name="速度性格",
        talents=DamageCalculatorTalentInput(hp=10, physical_defense=10, speed=10),
    )
    without_speed = _candidate_for_sort(
        nature_id="nature_speed",
        nature_name="速度性格",
        talents=DamageCalculatorTalentInput(hp=10, physical_defense=10, magic_defense=10),
    )

    assert (
        StandaloneDamageService._positive_nature_talent_missing(with_speed, nature_by_id)
        is False
    )
    assert (
        StandaloneDamageService._positive_nature_talent_missing(without_speed, nature_by_id)
        is True
    )


def test_infer_attacker_lowers_irrelevant_attack_stat_weight_for_magic_skill() -> None:
    """反推魔攻技能时，物攻+性格和物攻资质只降权，不硬排除。"""
    nature_by_id = {
        "nature_physical_attack": NatureDefinition(
            nature_id="nature_physical_attack",
            nature_name="物攻性格",
            positive_stat="physical_attack",
            negative_stat="magic_attack",
            positive_multiplier=1.2,
            negative_multiplier=0.9,
            neutral_multiplier=1.0,
        ),
        "nature_magic_attack": NatureDefinition(
            nature_id="nature_magic_attack",
            nature_name="魔攻性格",
            positive_stat="magic_attack",
            negative_stat="physical_attack",
            positive_multiplier=1.2,
            negative_multiplier=0.9,
            neutral_multiplier=1.0,
        ),
        "nature_speed": NatureDefinition(
            nature_id="nature_speed",
            nature_name="速度性格",
            positive_stat="speed",
            negative_stat="physical_attack",
            positive_multiplier=1.2,
            negative_multiplier=0.9,
            neutral_multiplier=1.0,
        ),
    }
    physical_related = _attacker_candidate_for_sort(
        "nature_physical_attack",
        "物攻性格",
        "生命+物攻+速度",
        talents=DamageCalculatorTalentInput(hp=10, physical_attack=10, speed=10),
        relevant_attack_stat="magic_attack",
    )
    magic_related = _attacker_candidate_for_sort(
        "nature_magic_attack",
        "魔攻性格",
        "生命+魔攻+速度",
        talents=DamageCalculatorTalentInput(hp=10, magic_attack=10, speed=10),
        relevant_attack_stat="magic_attack",
        is_relevant_attack_positive_nature=True,
    )
    speed_related = _attacker_candidate_for_sort(
        "nature_speed",
        "速度性格",
        "生命+魔攻+速度",
        talents=DamageCalculatorTalentInput(hp=10, magic_attack=10, speed=10),
        relevant_attack_stat="magic_attack",
    )

    assert (
        StandaloneDamageService._irrelevant_attack_stat_penalty(
            physical_related,
            nature_by_id,
            relevant_attack_stat="magic_attack",
        )
        == 2
    )
    assert (
        StandaloneDamageService._irrelevant_attack_stat_penalty(
            magic_related,
            nature_by_id,
            relevant_attack_stat="magic_attack",
        )
        == 0
    )
    assert (
        StandaloneDamageService._irrelevant_attack_stat_penalty(
            speed_related,
            nature_by_id,
            relevant_attack_stat="magic_attack",
        )
        == 0
    )


def test_infer_attacker_lowers_defensive_positive_nature_when_other_weights_equal() -> None:
    """反推攻击方同权重时，物防+/魔防+性格应排在生命/速度等非防御性格后面。"""
    nature_by_id = {
        "nature_speed": NatureDefinition(
            nature_id="nature_speed",
            nature_name="速度性格",
            positive_stat="speed",
            negative_stat="physical_attack",
            positive_multiplier=1.2,
            negative_multiplier=0.9,
            neutral_multiplier=1.0,
        ),
        "nature_physical_defense": NatureDefinition(
            nature_id="nature_physical_defense",
            nature_name="物防性格",
            positive_stat="physical_defense",
            negative_stat="physical_attack",
            positive_multiplier=1.2,
            negative_multiplier=0.9,
            neutral_multiplier=1.0,
        ),
        "nature_magic_defense": NatureDefinition(
            nature_id="nature_magic_defense",
            nature_name="魔防性格",
            positive_stat="magic_defense",
            negative_stat="physical_attack",
            positive_multiplier=1.2,
            negative_multiplier=0.9,
            neutral_multiplier=1.0,
        ),
    }
    speed_candidate = _attacker_candidate_for_sort(
        "nature_speed",
        "速度性格",
        "生命+魔攻+速度",
        talents=DamageCalculatorTalentInput(hp=10, magic_attack=10, speed=10),
        relevant_attack_stat="magic_attack",
    )
    physical_defense_candidate = _attacker_candidate_for_sort(
        "nature_physical_defense",
        "物防性格",
        "生命+魔攻+物防",
        talents=DamageCalculatorTalentInput(hp=10, magic_attack=10, physical_defense=10),
        relevant_attack_stat="magic_attack",
    )
    magic_defense_candidate = _attacker_candidate_for_sort(
        "nature_magic_defense",
        "魔防性格",
        "生命+魔攻+魔防",
        talents=DamageCalculatorTalentInput(hp=10, magic_attack=10, magic_defense=10),
        relevant_attack_stat="magic_attack",
    )

    assert (
        StandaloneDamageService._defensive_positive_nature_penalty(
            speed_candidate,
            nature_by_id,
        )
        == 0
    )
    assert (
        StandaloneDamageService._defensive_positive_nature_penalty(
            physical_defense_candidate,
            nature_by_id,
        )
        == 1
    )
    assert (
        StandaloneDamageService._defensive_positive_nature_penalty(
            magic_defense_candidate,
            nature_by_id,
        )
        == 1
    )


def _candidate_for_sort(
    *,
    nature_id: str,
    nature_name: str,
    talents: DamageCalculatorTalentInput,
) -> DamageCalculatorDefenderCandidateOut:
    return DamageCalculatorDefenderCandidateOut(
        rank=0,
        nature_id=nature_id,
        nature_name=nature_name,
        individual_talent_distribution=talents,
        relevant_defense_stat="physical_defense",
        hp_talent=talents.hp,
        defense_talent=talents.physical_defense,
        panel_stats=DamageCalculatorPanelOut(
            hp=300,
            physical_attack=120,
            physical_defense=120,
            magic_attack=100,
            magic_defense=100,
            speed=100,
        ),
        predicted_damage_value=100,
        predicted_damage_percent=30,
        delta_value=0,
        absolute_delta=0,
        delta_damage_percent=0,
        absolute_delta_damage_percent=0,
        combined_error=0,
        score=1,
        matched_within_tolerance=True,
    )


def _attacker_candidate_for_sort(
    nature_id: str,
    nature_name: str,
    template_name: str,
    *,
    talents: DamageCalculatorTalentInput | None = None,
    relevant_attack_stat: str = "physical_attack",
    is_relevant_attack_positive_nature: bool | None = None,
) -> DamageCalculatorAttackerCandidateOut:
    candidate_talents = talents or DamageCalculatorTalentInput(
        hp=10,
        physical_attack=10,
        speed=10,
    )
    attack_talent = int(getattr(candidate_talents, relevant_attack_stat))
    return DamageCalculatorAttackerCandidateOut(
        rank=0,
        template_name=template_name,
        nature_id=nature_id,
        nature_name=nature_name,
        individual_talent_distribution=candidate_talents,
        relevant_attack_stat=relevant_attack_stat,
        attack_talent=attack_talent,
        panel_stats=DamageCalculatorPanelOut(
            hp=300,
            physical_attack=180,
            physical_defense=100,
            magic_attack=100,
            magic_defense=100,
            speed=120,
        ),
        predicted_damage_value=100,
        delta_value=0,
        absolute_delta=0,
        score=1,
        matched_within_tolerance=True,
        is_relevant_attack_positive_nature=(
            nature_id == "nature_attack"
            if is_relevant_attack_positive_nature is None
            else is_relevant_attack_positive_nature
        ),
        has_relevant_attack_talent=attack_talent > 0,
    )


def test_infer_defender_integer_percent_uses_floor_display_rule() -> None:
    """整数扣血百分比按游戏显示向下取整，而不是要求小数完全相等。"""
    assert StandaloneDamageService._remaining_hp_percent_matches(
        before=100,
        after=80,
        predicted_damage_percent_exact=Decimal("20.58"),
    )
    assert not StandaloneDamageService._remaining_hp_percent_matches(
        before=100,
        after=80,
        predicted_damage_percent_exact=Decimal("21.00"),
    )
    assert StandaloneDamageService._remaining_hp_percent_matches(
        before=100,
        after=79.42,
        predicted_damage_percent_exact=Decimal("20.57"),
    )
