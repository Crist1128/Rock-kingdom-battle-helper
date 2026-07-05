"""实时面板估计服务测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import Side
from app.db.base import Base
from app.inference.observation_event import ObservationEventInput
from app.inference.observation_types import ObservationType
from app.models import battle as _battle_models  # noqa: F401
from app.models import estimate as _estimate_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState
from app.models.effect import BattleEffectInstance, BattleEffectSnapshot
from app.models.event import BattleEvent, DamageEvent, EffectChangeEvent, ResourceChangeEvent
from app.models.static import EffectDefinition, ElfDefinition, NatureDefinition
from app.schemas.estimate import EnemyDefaultConfigInput
from app.schemas.player_build import IndividualTalentInput
from app.services.battle_service import BattleService
from app.services.estimate_service import EstimateService
from app.utils.json import dumps_json, loads_json


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
    assert talents["physical_defense"] == 10
    assert talents["magic_attack"] == 10
    assert talents["speed"] == 0
    assert out.default_config["heuristic"]["archetype"] == "low_speed_high_attack"
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
    elf.base_speed_talent = 120
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
    assert out.default_config["heuristic"]["speed_threshold"] == 120


def test_auto_default_config_uses_hp_nature_for_strong_tank(
    db_session: Session,
) -> None:
    """强肉盾优先使用生命性格，并把三项 10 给生命/双抗。"""
    elf = db_session.get(ElfDefinition, "enemy_elf")
    assert elf is not None
    elf.base_hp_talent = 130
    elf.base_physical_attack_talent = 120
    elf.base_magic_attack_talent = 80
    elf.base_physical_defense_talent = 120
    elf.base_magic_defense_talent = 120
    elf.base_speed_talent = 90
    state = _enemy_state()
    db_session.add(state)

    EstimateService(db_session).create_for_enemy_state(
        "battle_estimate",
        state,
        commit=True,
    )
    out = EstimateService(db_session).get_estimate("battle_estimate", "enemy_elf")

    assert out.default_config is not None
    assert out.default_config["nature_id"] == "hp_plus_magic_attack_minus"
    talents = out.default_config["individual_talent_distribution"]
    assert talents["hp"] == 10
    assert talents["physical_defense"] == 10
    assert talents["magic_defense"] == 10
    assert talents["physical_attack"] == 0
    assert talents["speed"] == 0
    assert out.default_config["heuristic"]["archetype"] == "strong_tank"


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
                "snapshot_id": "snapshot_formula_1",
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
                "type_multiplier": 1,
                "stab_multiplier": 1,
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
    assert evidence[0].explanation is not None
    assert evidence[0].explanation["summary"] == "已根据本次观测生成属性约束。"
    assert evidence[0].explanation["event"] == {
        "source_event_id": "event_reverse_damage_1",
        "snapshot_id": "snapshot_formula_1",
    }
    assert evidence[0].explanation["formula"]["missing_inputs"] == ["defender_panel_stats"]
    assert evidence[0].explanation["formula"]["key_multipliers"]["base_power"] == "50"
    assert evidence[0].explanation["formula"]["key_multipliers"]["type_multiplier"] == "1"
    assert evidence[0].explanation["formula"]["key_multipliers"]["formula_factor"] == "45.1220"
    changes = {
        item["stat_key"]: item for item in evidence[0].explanation["constraint_changes"]
    }
    assert changes["hp"]["outcome"] == "new_constraint"
    assert changes["hp"]["merged"]["integer_min"] == 300
    assert changes["physical_defense"]["outcome"] == "new_constraint"
    assert changes["physical_defense"]["source_event_ids"] == ["event_reverse_damage_1"]


def test_evidence_explanation_marks_unmapped_snapshot_modifiers(
    db_session: Session,
) -> None:
    """快照里存在天气/状态但没有规则映射时，解释结构应明确标记 unknown。"""
    state = _enemy_state()
    db_session.add(state)
    service = EstimateService(db_session)
    service.create_for_enemy_state("battle_estimate", state, commit=True)

    out = service.record_observation(
        ObservationEventInput(
            battle_id="battle_estimate",
            enemy_elf_id="enemy_elf",
            event_id="event_snapshot_modifier_1",
            observation_type=ObservationType.DAMAGE_VALUE,
            observed_value=90,
            payload={
                "enemy_role": "defender",
                "defender_side": "enemy",
                "defender_elf_id": "enemy_elf",
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
                "snapshot_payload": [
                    {
                        "instance_id": "weather_rain_1",
                        "effect_id": "weather_rain",
                        "owner_scope": "field",
                        "owner_side": None,
                    },
                    {
                        "instance_id": "mark_guard_1",
                        "effect_id": "mark_guard",
                        "owner_scope": "elf",
                        "owner_side": "enemy",
                        "owner_elf_id": "enemy_elf",
                    },
                ],
            },
        ),
        commit=True,
    )

    assert out is not None
    assert "weather_modifier_rule_unmapped" in out.unknown_factors
    assert "active_effect_modifier_rules_unmapped" in out.unknown_factors
    evidence = service.list_evidence("battle_estimate", "enemy_elf")
    assert evidence[0].explanation is not None
    modifiers = evidence[0].explanation["modifiers"]
    assert modifiers["snapshot_effects"]["active_effect_count"] == 2
    assert modifiers["snapshot_effects"]["field_effect_count"] == 1
    assert modifiers["snapshot_effects"]["defender_effect_count"] == 1
    assert modifiers["unmapped_effect_modifier_count"] == 2


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
    assert talents["physical_defense"] == 10
    assert talents["speed"] == 0
    assert out.default_panel is not None
    assert 448 <= out.default_panel["hp"] <= 474


def test_replay_from_event_rebuilds_enemy_panel_estimates(db_session: Session) -> None:
    """事件重放会从已落库伤害事件重建实时面板估计和 evidence。"""
    state = _enemy_state()
    db_session.add(state)
    EstimateService(db_session).create_for_enemy_state("battle_estimate", state, commit=True)
    db_session.add(
        BattleEvent(
            event_id="event_replay_damage_1",
            battle_id="battle_estimate",
            turn_number=1,
            event_type="damage",
            actor_side="self",
            actor_elf_id="self_elf",
            target_side="enemy",
            target_elf_id="enemy_elf",
            skill_id="skill_replay_test",
            skill_confirmed=True,
            source="manual_input",
            manual_override=True,
            payload_json=dumps_json(
                {
                    "sync_observation": True,
                    "damage_tolerance": 999,
                    "percent_tolerance": 1,
                }
            ),
        )
    )
    db_session.add(
        DamageEvent(
            event_id="damage_event_replay_1",
            battle_id="battle_estimate",
            battle_event_id="event_replay_damage_1",
            attacker_side="self",
            attacker_elf_id="self_elf",
            defender_side="enemy",
            defender_elf_id="enemy_elf",
            skill_id="skill_replay_test",
            damage_display_type="single_damage",
            damage_value=76,
            hp_percent_before=100,
            hp_percent_after=83,
            hp_percent_delta=17,
            enemy_hp_percent_damage=17,
            formula_context_json=dumps_json(
                {
                    "formula_type": "attack",
                    "skill_category": "physical",
                    "observed_damage_value": 76,
                }
            ),
            calculation_confidence=0.0,
            manual_override=True,
        )
    )
    db_session.commit()

    result = BattleService(db_session).replay_from_event(
        "battle_estimate",
        "event_replay_damage_1",
    )
    out = EstimateService(db_session).get_estimate("battle_estimate", "enemy_elf")
    evidence = EstimateService(db_session).list_evidence("battle_estimate", "enemy_elf")

    assert result.status == "runtime_and_estimate_rebuilt"
    assert result.rebuilt_estimate_count == 1
    assert result.replayed_observation_count == 2
    assert result.runtime_replay_status == "partial_runtime_rebuilt"
    assert out.stat_constraints["hp"]["integer_min"] == 448
    assert out.stat_constraints["hp"]["integer_max"] == 474
    assert len(evidence) == 2
    assert {item.source_event_id for item in evidence} == {
        "replay:event_replay_damage_1:damage_value",
        "replay:event_replay_damage_1:hp_percent_delta",
    }


def test_replay_from_event_rebuilds_basic_runtime_state(db_session: Session) -> None:
    """事件重放会按非作废资源和切换事件重算基础 BattleElfState。"""
    db_session.add(
        ElfDefinition(
            elf_id="enemy_elf_bench",
            elf_name="测试敌方替补",
            avatar="",
            element_types_json=dumps_json(["normal"]),
            base_hp_talent=100,
            base_physical_attack_talent=100,
            base_physical_defense_talent=100,
            base_magic_attack_talent=90,
            base_magic_defense_talent=90,
            base_speed_talent=90,
        )
    )
    db_session.flush()
    active_enemy = _enemy_state()
    bench_enemy = _enemy_state(state_id="state_enemy_bench", elf_id="enemy_elf_bench")
    bench_enemy.is_active_elf = False
    bench_enemy.last_switch_turn = None
    active_enemy.current_hp_percent = 12
    active_enemy.energy = 1
    bench_enemy.current_hp_percent = 77
    db_session.add(active_enemy)
    db_session.add(bench_enemy)
    db_session.add(
        BattleEvent(
            event_id="event_runtime_damage_voided",
            battle_id="battle_estimate",
            turn_number=1,
            event_type="damage",
            actor_side="self",
            actor_elf_id="self_elf",
            target_side="enemy",
            target_elf_id="enemy_elf",
            source="manual_input",
            manual_override=True,
            is_voided=True,
        )
    )
    db_session.add(
        ResourceChangeEvent(
            event_id="resource_voided",
            battle_id="battle_estimate",
            battle_event_id="event_runtime_damage_voided",
            resource_type="hp",
            change_type="damage",
            target_side="enemy",
            target_elf_id="enemy_elf",
            value_type="percent",
            value=50,
            before_value=100,
            after_value=50,
            manual_override=True,
        )
    )
    db_session.add(
        BattleEvent(
            event_id="event_runtime_damage_kept",
            battle_id="battle_estimate",
            turn_number=1,
            event_type="damage",
            actor_side="self",
            actor_elf_id="self_elf",
            target_side="enemy",
            target_elf_id="enemy_elf",
            source="manual_input",
            manual_override=True,
        )
    )
    db_session.add(
        ResourceChangeEvent(
            event_id="resource_kept",
            battle_id="battle_estimate",
            battle_event_id="event_runtime_damage_kept",
            resource_type="hp",
            change_type="damage",
            target_side="enemy",
            target_elf_id="enemy_elf",
            value_type="percent",
            value=17,
            before_value=100,
            after_value=83,
            manual_override=True,
        )
    )
    db_session.add(
        BattleEvent(
            event_id="event_runtime_energy",
            battle_id="battle_estimate",
            turn_number=1,
            event_type="energy_change",
            actor_side="enemy",
            actor_elf_id="enemy_elf",
            target_side="enemy",
            target_elf_id="enemy_elf",
            source="manual_input",
            manual_override=True,
        )
    )
    db_session.add(
        ResourceChangeEvent(
            event_id="resource_energy",
            battle_id="battle_estimate",
            battle_event_id="event_runtime_energy",
            resource_type="energy",
            change_type="consume",
            target_side="enemy",
            target_elf_id="enemy_elf",
            value_type="value",
            value=3,
            before_value=10,
            after_value=7,
            manual_override=True,
        )
    )
    db_session.add(
        BattleEvent(
            event_id="event_runtime_switch",
            battle_id="battle_estimate",
            turn_number=2,
            event_type="switch_elf",
            actor_side="enemy",
            actor_elf_id="enemy_elf",
            target_side="enemy",
            target_elf_id="enemy_elf_bench",
            source="manual_input",
            manual_override=True,
            payload_json=dumps_json(
                {"from_elf_id": "enemy_elf", "to_elf_id": "enemy_elf_bench"}
            ),
        )
    )
    db_session.commit()

    result = BattleService(db_session).replay_from_event(
        "battle_estimate",
        "event_runtime_damage_kept",
    )
    active_after = db_session.get(BattleElfState, "state_enemy")
    bench_after = db_session.get(BattleElfState, "state_enemy_bench")
    battle = db_session.get(Battle, "battle_estimate")

    assert result.runtime_resource_event_count == 2
    assert result.runtime_switch_event_count == 1
    assert active_after is not None
    assert active_after.current_hp_percent == 83
    assert active_after.energy == 7
    assert active_after.is_active_elf is False
    assert bench_after is not None
    assert bench_after.current_hp_percent == 100
    assert bench_after.is_active_elf is True
    assert battle is not None
    assert battle.enemy_active_elf_id == "enemy_elf_bench"


def test_replay_from_event_rebuilds_effect_instances(db_session: Session) -> None:
    """事件重放会按 EffectChangeEvent 重建最终生效状态实例。"""
    state = _enemy_state()
    db_session.add(state)
    db_session.add(
        EffectDefinition(
            effect_id="effect_replay_mark",
            effect_name="重放测试印记",
            category="mark",
            polarity="buff",
            display_group="mark",
            owner_scope="elf",
            target_scope="elf",
            attach_target_type="elf",
            stack_rule="replace",
            max_layers=5,
            default_layers=1,
        )
    )
    db_session.flush()
    db_session.add(
        BattleEffectInstance(
            instance_id="effect_instance_stale",
            battle_id="battle_estimate",
            effect_id="effect_replay_mark",
            category="mark",
            owner_scope="elf",
            owner_side="enemy",
            owner_elf_id="enemy_elf",
            layers=9,
            is_active=True,
            manual_override=True,
        )
    )
    db_session.add(
        BattleEvent(
            event_id="event_effect_apply_active",
            battle_id="battle_estimate",
            turn_number=1,
            event_type="effect_apply",
            target_side="enemy",
            target_elf_id="enemy_elf",
            source="manual_input",
            manual_override=True,
        )
    )
    db_session.add(
        EffectChangeEvent(
            event_id="effect_change_apply_active",
            battle_id="battle_estimate",
            battle_event_id="event_effect_apply_active",
            turn_number=1,
            change_type="apply",
            effect_instance_id="effect_instance_active",
            effect_id="effect_replay_mark",
            effect_name="重放测试印记",
            category="mark",
            target_side="enemy",
            target_elf_id="enemy_elf",
            owner_scope="elf",
            layers_before=None,
            layers_after=2,
            duration_after=3,
            source="manual_input",
            manual_override=True,
        )
    )
    db_session.add(
        BattleEvent(
            event_id="event_effect_apply_removed",
            battle_id="battle_estimate",
            turn_number=1,
            event_type="effect_apply",
            target_side="enemy",
            target_elf_id="enemy_elf",
            source="manual_input",
            manual_override=True,
        )
    )
    db_session.add(
        EffectChangeEvent(
            event_id="effect_change_apply_removed",
            battle_id="battle_estimate",
            battle_event_id="event_effect_apply_removed",
            turn_number=1,
            change_type="apply",
            effect_instance_id="effect_instance_removed",
            effect_id="effect_replay_mark",
            effect_name="重放测试印记",
            category="mark",
            target_side="enemy",
            target_elf_id="enemy_elf",
            owner_scope="elf",
            layers_before=None,
            layers_after=1,
            duration_after=2,
            source="manual_input",
            manual_override=True,
        )
    )
    db_session.add(
        BattleEvent(
            event_id="event_effect_remove",
            battle_id="battle_estimate",
            turn_number=2,
            event_type="effect_remove",
            target_side="enemy",
            target_elf_id="enemy_elf",
            source="manual_input",
            manual_override=True,
        )
    )
    db_session.add(
        EffectChangeEvent(
            event_id="effect_change_remove",
            battle_id="battle_estimate",
            battle_event_id="event_effect_remove",
            turn_number=2,
            change_type="remove",
            effect_instance_id="effect_instance_removed",
            effect_id="effect_replay_mark",
            effect_name="重放测试印记",
            category="mark",
            target_side="enemy",
            target_elf_id="enemy_elf",
            owner_scope="elf",
            layers_before=1,
            layers_after=0,
            duration_after=0,
            source="manual_input",
            manual_override=True,
        )
    )
    db_session.commit()

    result = BattleService(db_session).replay_from_event(
        "battle_estimate",
        "event_effect_apply_active",
    )
    stale = db_session.get(BattleEffectInstance, "effect_instance_stale")
    active = db_session.get(BattleEffectInstance, "effect_instance_active")
    removed = db_session.get(BattleEffectInstance, "effect_instance_removed")

    assert result.runtime_effect_change_event_count == 3
    assert result.runtime_active_effect_count == 1
    assert result.runtime_snapshot_id is not None
    assert result.runtime_snapshot_rebuilt_count == 3
    assert result.runtime_snapshot_effect_count == 1
    assert stale is None
    assert active is not None
    assert active.is_active is True
    assert active.layers == 2
    assert active.remaining_turns == 3
    assert active.expire_turn == 4
    assert removed is not None
    assert removed.is_active is False
    assert removed.layers == 0
    battle = db_session.get(Battle, "battle_estimate")
    assert battle is not None
    assert battle.current_snapshot_id == result.runtime_snapshot_id
    snapshot = db_session.get(BattleEffectSnapshot, result.runtime_snapshot_id)
    assert snapshot is not None
    assert snapshot.source_event_id == "event_effect_remove"
    snapshot_items = loads_json(snapshot.full_snapshot_json, [])
    assert len(snapshot_items) == 1
    assert snapshot_items[0]["instance_id"] == "effect_instance_active"
    assert snapshot_items[0]["layers"] == 2

    event_apply_active = db_session.get(BattleEvent, "event_effect_apply_active")
    event_apply_removed = db_session.get(BattleEvent, "event_effect_apply_removed")
    event_remove = db_session.get(BattleEvent, "event_effect_remove")
    assert event_apply_active is not None and event_apply_active.snapshot_id
    assert event_apply_removed is not None and event_apply_removed.snapshot_id
    assert event_remove is not None and event_remove.snapshot_id == result.runtime_snapshot_id

    apply_snapshot = db_session.get(BattleEffectSnapshot, event_apply_active.snapshot_id)
    middle_snapshot = db_session.get(BattleEffectSnapshot, event_apply_removed.snapshot_id)
    assert apply_snapshot is not None
    assert middle_snapshot is not None
    assert apply_snapshot.source_event_id == "event_effect_apply_active"
    assert middle_snapshot.source_event_id == "event_effect_apply_removed"
    assert len(loads_json(apply_snapshot.full_snapshot_json, [])) == 1
    assert len(loads_json(middle_snapshot.full_snapshot_json, [])) == 2

    first_replay_snapshot_ids = {
        event_apply_active.snapshot_id,
        event_apply_removed.snapshot_id,
        event_remove.snapshot_id,
    }
    second_result = BattleService(db_session).replay_from_event(
        "battle_estimate",
        "event_effect_apply_active",
    )
    second_replay_snapshot_ids = {
        db_session.get(BattleEvent, "event_effect_apply_active").snapshot_id,
        db_session.get(BattleEvent, "event_effect_apply_removed").snapshot_id,
        db_session.get(BattleEvent, "event_effect_remove").snapshot_id,
    }
    assert second_result.runtime_snapshot_rebuilt_count == 3
    assert first_replay_snapshot_ids.isdisjoint(second_replay_snapshot_ids)
    old_snapshots = db_session.scalars(
        select(BattleEffectSnapshot).where(
            BattleEffectSnapshot.snapshot_id.in_(first_replay_snapshot_ids)
        )
    ).all()
    assert {item.deleted_at is not None for item in old_snapshots} == {True}


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
    assert evidence[0].explanation is not None
    assert evidence[0].explanation["summary"] == "本次观测与已有约束存在冲突，需要人工复核。"
    conflict_changes = {
        item["stat_key"]: item for item in evidence[0].explanation["constraint_changes"]
    }
    assert conflict_changes["physical_defense"]["outcome"] == "conflict"
    assert conflict_changes["physical_defense"]["previous"]["integer_min"] == 100
    assert conflict_changes["physical_defense"]["incoming"]["integer_min"] == 292


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


def _enemy_state(
    *,
    state_id: str = "state_enemy",
    elf_id: str = "enemy_elf",
    is_active_elf: bool = True,
) -> BattleElfState:
    return BattleElfState(
        state_id=state_id,
        battle_id="battle_estimate",
        side=Side.ENEMY.value,
        elf_id=elf_id,
        elf_name="测试敌方精灵",
        avatar="",
        panel_stats_json=dumps_json({}),
        current_hp_value=None,
        current_hp_percent=100.0,
        energy=10,
        skill_ids_json=dumps_json([]),
        confirmed_skill_ids_json=dumps_json([]),
        active_effect_instance_ids_json=dumps_json([]),
        is_active_elf=is_active_elf,
        is_defeated=False,
        manual_override=True,
    )
