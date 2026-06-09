"""实时面板估计服务测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import Side
from app.db.base import Base
from app.inference.observation_matcher import ObservationEventInput
from app.inference.observation_types import ObservationType
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import estimate as _estimate_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState
from app.models.static import ElfDefinition, NatureDefinition
from app.schemas.estimate import EnemyDefaultConfigInput
from app.schemas.player_build import IndividualTalentInput
from app.services.estimate_service import EstimateService
from app.utils.json import dumps_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建隔离内存数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    session = session_factory()
    session.add(Battle(battle_id="battle_estimate", battle_name="estimate test"))
    session.add(
        ElfDefinition(
            elf_id="enemy_elf",
            elf_name="测试敌方精灵",
            avatar="",
            element_types_json=dumps_json(["normal"]),
            base_hp_talent=100,
            base_physical_attack_talent=110,
            base_physical_defense_talent=90,
            base_magic_attack_talent=120,
            base_magic_defense_talent=80,
            base_speed_talent=105,
        )
    )
    session.add_all(
        [
            NatureDefinition(
                nature_id="magic_attack_plus_physical_attack_minus",
                nature_name="加魔攻减物攻",
                positive_stat="magic_attack",
                negative_stat="physical_attack",
            ),
            NatureDefinition(
                nature_id="physical_attack_plus_magic_attack_minus",
                nature_name="加物攻减魔攻",
                positive_stat="physical_attack",
                negative_stat="magic_attack",
            ),
            NatureDefinition(
                nature_id="hp_plus_magic_attack_minus",
                nature_name="hp_plus_magic_attack_minus",
                positive_stat="hp",
                negative_stat="magic_attack",
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


def test_create_for_enemy_state_uses_auto_default_config(db_session: Session) -> None:
    """创建敌方估计档案时按种族值生成默认配置。"""
    state = _enemy_state()
    db_session.add(state)

    estimate = EstimateService(db_session).create_for_enemy_state(
        "battle_estimate",
        state,
        commit=True,
    )
    out = EstimateService(db_session).get_estimate("battle_estimate", "enemy_elf")

    assert estimate.elf_id == "enemy_elf"
    assert out.default_config is not None
    assert out.default_config["nature_id"] == "magic_attack_plus_physical_attack_minus"
    talents = out.default_config["individual_talent_distribution"]
    assert talents["hp"] == 10
    assert talents["magic_attack"] == 10
    assert talents["speed"] == 10
    assert out.estimated_panel is not None
    assert out.estimated_panel["source"] == "auto_default_config"
    assert out.unknown_factors


def test_auto_default_config_uses_speed_nature_for_fast_physical_elf(
    db_session: Session,
) -> None:
    """速度高且物攻更高时，默认加速度减魔攻，资质点生命/物攻/速度。"""
    elf = db_session.get(ElfDefinition, "enemy_elf")
    assert elf is not None
    elf.base_physical_attack_talent = 130
    elf.base_magic_attack_talent = 90
    elf.base_speed_talent = 115
    state = _enemy_state()
    db_session.add(state)

    EstimateService(db_session).create_for_enemy_state(
        "battle_estimate",
        state,
        commit=True,
    )
    out = EstimateService(db_session).get_estimate("battle_estimate", "enemy_elf")

    assert out.default_config is not None
    assert out.default_config["nature_id"] == "speed_plus_magic_attack_minus"
    talents = out.default_config["individual_talent_distribution"]
    assert talents["hp"] == 10
    assert talents["physical_attack"] == 10
    assert talents["magic_attack"] == 0
    assert talents["speed"] == 10


def test_update_default_config_calculates_display_panel(db_session: Session) -> None:
    """玩家选择默认配置后，估计档案应保存配置并计算展示面板。"""
    state = _enemy_state()
    db_session.add(state)
    service = EstimateService(db_session)
    service.create_for_enemy_state("battle_estimate", state, commit=True)

    out = service.update_default_config(
        "battle_estimate",
        "enemy_elf",
        EnemyDefaultConfigInput(
            preset="custom",
            nature_id="magic_attack_plus_physical_attack_minus",
            individual_talent_distribution=IndividualTalentInput(
                hp=10,
                physical_attack=0,
                physical_defense=0,
                magic_attack=10,
                magic_defense=0,
                speed=10,
            ),
        ),
    )

    assert out.default_config is not None
    assert out.default_config["nature_id"] == "magic_attack_plus_physical_attack_minus"
    assert out.default_panel is not None
    assert out.estimated_panel == out.default_panel
    assert out.estimated_panel["magic_attack"] > out.estimated_panel["physical_attack"]
    assert out.confidence["hp"] == "default_config"


def test_record_observation_derives_hp_and_defense_constraints(
    db_session: Session,
) -> None:
    """伤害值和扣血百分比齐全时，实时估计应写入 HP 与防御范围。"""
    state = _enemy_state()
    db_session.add(state)
    service = EstimateService(db_session)
    service.create_for_enemy_state("battle_estimate", state, commit=True)

    out = service.record_observation(
        ObservationEventInput(
            battle_id="battle_estimate",
            enemy_elf_id="enemy_elf",
            event_id="event_reverse_damage_1",
            observation_type=ObservationType.DAMAGE_VALUE,
            observed_value=90,
            payload={
                "enemy_role": "defender",
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
                "observed_hp_percent_delta": 30,
                "percent_tolerance": 0,
            },
        ),
        commit=True,
    )

    assert out is not None
    assert out.stat_constraints["physical_defense"]["status"] == "formula_constraint_derived"
    assert out.stat_constraints["physical_defense"]["integer_min"] == 100
    assert out.stat_constraints["physical_defense"]["integer_max"] == 100
    assert out.stat_constraints["hp"]["integer_min"] == 300
    assert out.stat_constraints["hp"]["integer_max"] == 300
    assert out.confidence["physical_defense"] == "formula_constraint_derived"
    assert out.confidence["hp"] == "formula_constraint_derived"

    evidence = service.list_evidence("battle_estimate", "enemy_elf")
    assert evidence[0].confidence == "formula_constraint_derived"
    assert evidence[0].inferred_stats is not None
    assert evidence[0].inferred_stats["physical_defense"]["integer_min"] == 100
    assert evidence[0].inferred_stats["hp"]["integer_max"] == 300


def test_floor_remaining_percent_derives_usable_hp_constraint(
    db_session: Session,
) -> None:
    """整数剩余百分比应反推出可用 HP 区间，不能生成空区间后被展开逻辑跳过。"""
    state = _enemy_state()
    db_session.add(state)
    service = EstimateService(db_session)
    service.create_for_enemy_state("battle_estimate", state, commit=True)

    out = service.record_observation(
        ObservationEventInput(
            battle_id="battle_estimate",
            enemy_elf_id="enemy_elf",
            event_id="event_floor_hp_1",
            observation_type=ObservationType.DAMAGE_VALUE,
            observed_value=76,
            payload={
                "enemy_role": "defender",
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
                "damage_tolerance": 999,
                "observed_hp_percent_before": 100,
                "observed_hp_percent_after": 83,
                "percent_display_mode": "floor_remaining_percent",
            },
        ),
        commit=True,
    )

    assert out is not None
    hp_constraint = out.stat_constraints["hp"]
    assert hp_constraint["integer_min"] == 448
    assert hp_constraint["integer_max"] == 474
    assert hp_constraint["status"] == "formula_constraint_derived"


def test_hp_only_observation_repairs_invalid_player_default_to_base_heuristic(
    db_session: Session,
) -> None:
    """HP 约束应把冲突的玩家默认配置回填为种族值启发式常见配置。"""
    elf = db_session.get(ElfDefinition, "enemy_elf")
    assert elf is not None
    elf.base_hp_talent = 135
    elf.base_physical_attack_talent = 130
    elf.base_magic_attack_talent = 90
    elf.base_speed_talent = 105
    state = _enemy_state()
    db_session.add(state)
    service = EstimateService(db_session)
    service.create_for_enemy_state("battle_estimate", state, commit=True)

    stale = service.update_default_config(
        "battle_estimate",
        "enemy_elf",
        EnemyDefaultConfigInput(
            preset="custom",
            nature_id="hp_plus_magic_attack_minus",
            individual_talent_distribution=IndividualTalentInput(
                hp=10,
                physical_attack=10,
                physical_defense=0,
                magic_attack=0,
                magic_defense=0,
                speed=10,
            ),
        ),
    )
    assert stale.default_panel is not None
    assert stale.default_panel["hp"] > 474

    out = service.record_observation(
        ObservationEventInput(
            battle_id="battle_estimate",
            enemy_elf_id="enemy_elf",
            event_id="event_floor_hp_repair_default_1",
            observation_type=ObservationType.DAMAGE_VALUE,
            observed_value=76,
            payload={
                "enemy_role": "defender",
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
                "damage_tolerance": 999,
                "observed_hp_percent_before": 100,
                "observed_hp_percent_after": 83,
                "percent_display_mode": "floor_remaining_percent",
            },
        ),
        commit=True,
    )

    assert out is not None
    assert out.stat_constraints["hp"]["integer_min"] == 448
    assert out.stat_constraints["physical_defense"]["status"] == "observed_pending_formula"
    assert out.default_config is not None
    assert out.default_config["nature_id"] == "physical_attack_plus_magic_attack_minus"
    assert out.default_config["preset"] == "auto_repaired_by_realtime_constraints"
    talents = out.default_config["individual_talent_distribution"]
    assert talents["hp"] == 10
    assert talents["physical_attack"] == 10
    assert talents["speed"] == 10
    assert out.default_panel is not None
    assert 448 <= out.default_panel["hp"] <= 474


def test_conflicting_numeric_constraints_are_recorded_in_evidence(
    db_session: Session,
) -> None:
    """多次推导产生空交集时，应保留冲突状态并写入 evidence。"""
    state = _enemy_state()
    db_session.add(state)
    service = EstimateService(db_session)
    service.create_for_enemy_state("battle_estimate", state, commit=True)

    base_payload = {
        "enemy_role": "defender",
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
    }
    service.record_observation(
        ObservationEventInput(
            battle_id="battle_estimate",
            enemy_elf_id="enemy_elf",
            event_id="event_conflict_1",
            observation_type=ObservationType.DAMAGE_VALUE,
            observed_value=90,
            payload=base_payload,
        ),
        commit=True,
    )
    out = service.record_observation(
        ObservationEventInput(
            battle_id="battle_estimate",
            enemy_elf_id="enemy_elf",
            event_id="event_conflict_2",
            observation_type=ObservationType.DAMAGE_VALUE,
            observed_value=30,
            payload=base_payload,
        ),
        commit=True,
    )

    assert out is not None
    assert out.stat_constraints["physical_defense"]["status"] == "constraint_conflict"
    assert out.confidence["physical_defense"] == "constraint_conflict"
    evidence = service.list_evidence("battle_estimate", "enemy_elf")
    assert evidence[0].confidence == "constraint_conflict"
    assert evidence[0].conflict is not None
    assert evidence[0].conflict["conflicts"][0]["stat_key"] == "physical_defense"


def test_observation_repairs_default_config_when_existing_choice_violates_constraints(
    db_session: Session,
) -> None:
    """已有推导后，若当前默认配置冲突，应自动回填当前约束命中的配置。"""
    elf = db_session.get(ElfDefinition, "enemy_elf")
    assert elf is not None
    elf.base_physical_attack_talent = 130
    elf.base_magic_attack_talent = 90
    elf.base_speed_talent = 90
    state = _enemy_state()
    db_session.add(state)
    service = EstimateService(db_session)
    service.create_for_enemy_state("battle_estimate", state, commit=True)

    estimate = service._require_estimate("battle_estimate", "enemy_elf")
    estimate.default_config_json = dumps_json(
        {
            "preset": "stale_player_choice",
            "nature_id": "magic_attack_plus_physical_attack_minus",
            "individual_talent_distribution": {
                "hp": 10,
                "physical_attack": 0,
                "physical_defense": 0,
                "magic_attack": 10,
                "magic_defense": 0,
                "speed": 10,
            },
        }
    )
    estimate.default_panel_json = dumps_json(
        {
            "hp": 391,
            "physical_attack": 168,
            "physical_defense": 159,
            "magic_attack": 260,
            "magic_defense": 148,
            "speed": 209,
        }
    )
    estimate.estimated_panel_json = estimate.default_panel_json
    db_session.commit()

    out = service.record_observation(
        ObservationEventInput(
            battle_id="battle_estimate",
            enemy_elf_id="enemy_elf",
            event_id="event_repair_default_1",
            observation_type=ObservationType.DAMAGE_VALUE,
            observed_value=123,
            payload={
                "enemy_role": "attacker",
                "defender_panel_stats": {
                    "hp": 300,
                    "physical_attack": 100,
                    "physical_defense": 100,
                    "magic_attack": 100,
                    "magic_defense": 100,
                    "speed": 100,
                },
                "skill_category": "physical",
                "base_power": 50,
                "damage_tolerance": 0,
            },
        ),
        commit=True,
    )

    assert out is not None
    assert out.stat_constraints["physical_attack"]["integer_min"] == 273
    assert out.default_config is not None
    assert out.default_config["nature_id"] == "physical_attack_plus_magic_attack_minus"
    talents = out.default_config["individual_talent_distribution"]
    assert talents["physical_attack"] > 0
    assert out.default_panel is not None
    assert out.default_panel["physical_attack"] == 273


def _enemy_state() -> BattleElfState:
    return BattleElfState(
        state_id="state_enemy",
        battle_id="battle_estimate",
        side=Side.ENEMY.value,
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
