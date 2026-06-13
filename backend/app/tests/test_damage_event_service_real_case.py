"""伤害事件服务的真实样例回归测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import estimate as _estimate_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState
from app.models.effect import BattleEffectInstance
from app.models.estimate import EnemyPanelEstimate
from app.models.event import BattleEvent, ResourceChangeEvent
from app.models.static import EffectDefinition, ElfDefinition, NatureDefinition, SkillDefinition
from app.schemas.event import DamageDisplayType, DamageEventCreate
from app.services.damage_event_service import DamageEventService
from app.utils.json import dumps_json, loads_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建隔离的内存数据库。"""
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
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_damage_event_service_calculates_huoshen_blow_fire_case(db_session: Session) -> None:
    """火神使用吹火攻击龙息帕尔时，服务路径应能复算出 76 伤害。"""
    db_session.add_all(
        [
            Battle(
                battle_id="battle_real_case",
                battle_name="真实样例",
                phase="battle",
                turn_number=1,
                self_active_elf_id="elf_huoshen",
                enemy_active_elf_id="elf_longxi_paer",
            ),
            ElfDefinition(
                elf_id="elf_huoshen",
                elf_name="火神",
                avatar="",
                element_types_json=dumps_json(["fire"]),
                base_hp_talent=0,
                base_physical_attack_talent=0,
                base_physical_defense_talent=0,
                base_magic_attack_talent=0,
                base_magic_defense_talent=0,
                base_speed_talent=0,
            ),
            ElfDefinition(
                elf_id="elf_longxi_paer",
                elf_name="龙息帕尔",
                avatar="",
                element_types_json=dumps_json(["dark"]),
                base_hp_talent=0,
                base_physical_attack_talent=0,
                base_physical_defense_talent=0,
                base_magic_attack_talent=0,
                base_magic_defense_talent=0,
                base_speed_talent=0,
            ),
            SkillDefinition(
                skill_id="skill_blow_fire",
                skill_name="吹火",
                skill_icon=None,
                element_type="fire",
                skill_category="physical",
                base_power=50,
                base_energy_cost=0,
                priority_modifier=0,
            ),
        ]
    )
    db_session.commit()

    db_session.add_all(
        [
            BattleElfState(
                state_id="state_huoshen",
                battle_id="battle_real_case",
                side="self",
                elf_id="elf_huoshen",
                elf_name="火神",
                avatar="",
                panel_stats_json=dumps_json(
                    {
                        "hp": 410,
                        "physical_attack": 277,
                        "physical_defense": 163,
                        "magic_attack": 119,
                        "magic_defense": 139,
                        "speed": 229,
                    }
                ),
                current_hp_value=410,
                current_hp_percent=100,
                is_active_elf=True,
            ),
            BattleElfState(
                state_id="state_longxi_paer",
                battle_id="battle_real_case",
                side="enemy",
                elf_id="elf_longxi_paer",
                elf_name="龙息帕尔",
                avatar="",
                panel_stats_json=dumps_json(
                    {
                        "hp": 442,
                        "physical_attack": 270,
                        "physical_defense": 204,
                        "magic_attack": 116,
                        "magic_defense": 156,
                        "speed": 203,
                    }
                ),
                current_hp_value=442,
                current_hp_percent=100,
                is_active_elf=True,
            ),
        ]
    )
    db_session.commit()

    result = DamageEventService(db_session).create_damage_event(
        "battle_real_case",
        DamageEventCreate(
            turn_number=1,
            attacker_side="self",
            attacker_elf_id="elf_huoshen",
            defender_side="enemy",
            defender_elf_id="elf_longxi_paer",
            skill_id="skill_blow_fire",
            skill_confirmed=True,
            damage_display_type=DamageDisplayType.SINGLE_DAMAGE,
            damage_value=76,
            condition_flags={"actor_moves_before_target": True},
            hp_percent_before=100,
            hp_percent_after=83,
        ),
    )

    assert result.inference_result["status"] == "calculated"
    assert result.inference_result["confidence"] == 1.0
    assert result.damage_event.calculation_confidence == 1.0

    formula_context = loads_json(result.damage_event.formula_context_json, {})
    event_payload = loads_json(result.battle_event.payload_json, {})
    assert event_payload["condition_flags"]["actor_moves_before_target"] is True
    assert formula_context["rule_resolution_details"]["condition_flags"] == {
        "actor_moves_before_target": True
    }
    assert formula_context["skill_category"] == "physical"
    assert formula_context["base_power"] == 50
    assert formula_context["stab_multiplier"] == "1.25"
    assert formula_context["type_multiplier"] == "1"
    assert formula_context["attacker_panel_stats"]["physical_attack"] == 277
    assert formula_context["defender_panel_stats"]["physical_defense"] == 204


def test_damage_event_service_auto_applies_latest_same_turn_defense_action(
    db_session: Session,
) -> None:
    """同回合先记录防御技能后，下一次命中该精灵的伤害应自动带入减伤上下文。"""
    db_session.add_all(
        [
            Battle(
                battle_id="battle_defense_response",
                battle_name="防御应对闭环",
                phase="battle",
                turn_number=1,
                self_active_elf_id="elf_attacker",
                enemy_active_elf_id="elf_defender",
            ),
            ElfDefinition(
                elf_id="elf_attacker",
                elf_name="攻击方",
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
                elf_id="elf_defender",
                elf_name="防御方",
                avatar="",
                element_types_json=dumps_json(["normal"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
            SkillDefinition(
                skill_id="skill_fire_hit",
                skill_name="火焰测试",
                skill_icon=None,
                element_type="fire",
                skill_category="physical",
                base_power=50,
                base_energy_cost=0,
                priority_modifier=0,
            ),
            SkillDefinition(
                skill_id="skill_defense",
                skill_name="防御",
                skill_icon=None,
                element_type="normal",
                skill_category="status",
                base_power=None,
                base_energy_cost=0,
                priority_modifier=0,
                damage_rule_json=dumps_json(
                    {
                        "damage_type": "defense_modifier",
                        "damage_reduction": 0.7,
                        "active": True,
                        "response_rule": {
                            "target": "attack",
                            "condition": "response_attack_success",
                        },
                    }
                ),
            ),
        ]
    )
    db_session.commit()
    db_session.add_all(
        [
            BattleElfState(
                state_id="state_attacker",
                battle_id="battle_defense_response",
                side="self",
                elf_id="elf_attacker",
                elf_name="攻击方",
                avatar="",
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
                current_hp_value=300,
                current_hp_percent=100,
                is_active_elf=True,
            ),
            BattleElfState(
                state_id="state_defender",
                battle_id="battle_defense_response",
                side="enemy",
                elf_id="elf_defender",
                elf_name="防御方",
                avatar="",
                panel_stats_json=dumps_json(
                    {
                        "hp": 300,
                        "physical_attack": 100,
                        "physical_defense": 100,
                        "magic_attack": 100,
                        "magic_defense": 100,
                        "speed": 100,
                    }
                ),
                current_hp_value=300,
                current_hp_percent=100,
                is_active_elf=True,
            ),
        ]
    )
    db_session.commit()
    defense_event = BattleEvent(
        event_id="event_defense_action",
        battle_id="battle_defense_response",
        turn_number=1,
        action_order=1,
        event_type="skill_use",
        actor_side="enemy",
        actor_elf_id="elf_defender",
        target_side="enemy",
        target_elf_id="elf_defender",
        skill_id="skill_defense",
        skill_confirmed=True,
        source="manual_input",
        manual_override=False,
    )
    db_session.add(defense_event)
    db_session.commit()

    first = DamageEventService(db_session).create_damage_event(
        "battle_defense_response",
        DamageEventCreate(
            turn_number=1,
            attacker_side="self",
            attacker_elf_id="elf_attacker",
            defender_side="enemy",
            defender_elf_id="elf_defender",
            skill_id="skill_fire_hit",
            skill_confirmed=True,
            damage_display_type=DamageDisplayType.SINGLE_DAMAGE,
            damage_value=33,
            sync_observation=False,
        ),
    )
    second = DamageEventService(db_session).create_damage_event(
        "battle_defense_response",
        DamageEventCreate(
            turn_number=1,
            attacker_side="self",
            attacker_elf_id="elf_attacker",
            defender_side="enemy",
            defender_elf_id="elf_defender",
            skill_id="skill_fire_hit",
            skill_confirmed=True,
            damage_display_type=DamageDisplayType.SINGLE_DAMAGE,
            damage_value=112,
            sync_observation=False,
        ),
    )

    first_context = loads_json(first.damage_event.formula_context_json, {})
    first_payload = loads_json(first.battle_event.payload_json, {})
    second_context = loads_json(second.damage_event.formula_context_json, {})

    assert first.inference_result["status"] == "calculated"
    assert first.damage_event.calculation_confidence == 1.0
    assert first_payload["defense_skill_id"] == "skill_defense"
    assert first_payload["defense_response_event_id"] == "event_defense_action"
    assert first_payload["response_attack_success"] is True
    assert first_context["defense_skill_id"] == "skill_defense"
    assert first_context["response_attack_success"] is True
    assert first_context["rule_resolution_details"]["damage_reductions"]["items"][0] == {
        "source_id": "skill_defense",
        "source_type": "defense_modifier",
        "reduction": "0.7",
        "certainty": "known",
    }
    assert second.inference_result["status"] == "calculated"
    assert second_context["defense_skill_id"] is None
    assert "damage_reductions" not in second_context["rule_resolution_details"]


def test_damage_event_service_records_self_exact_hp_when_enemy_attacks(
    db_session: Session,
) -> None:
    """龙息帕尔攻击火神时，应使用我方可见精确 HP 更新状态和资源事件。"""
    db_session.add_all(
        [
            Battle(
                battle_id="battle_self_damaged",
                battle_name="真实样例-我方受击",
                phase="battle",
                turn_number=2,
                self_active_elf_id="elf_huoshen",
                enemy_active_elf_id="elf_longxi_paer",
            ),
            ElfDefinition(
                elf_id="elf_huoshen",
                elf_name="火神",
                avatar="",
                element_types_json=dumps_json(["fire"]),
                base_hp_talent=0,
                base_physical_attack_talent=0,
                base_physical_defense_talent=0,
                base_magic_attack_talent=0,
                base_magic_defense_talent=0,
                base_speed_talent=0,
            ),
            ElfDefinition(
                elf_id="elf_longxi_paer",
                elf_name="龙息帕尔",
                avatar="",
                element_types_json=dumps_json(["dark"]),
                base_hp_talent=0,
                base_physical_attack_talent=0,
                base_physical_defense_talent=0,
                base_magic_attack_talent=0,
                base_magic_defense_talent=0,
                base_speed_talent=0,
            ),
            SkillDefinition(
                skill_id="skill_bat",
                skill_name="蝙蝠",
                skill_icon=None,
                element_type="dark",
                skill_category="physical",
                base_power=50,
                base_energy_cost=0,
                priority_modifier=0,
            ),
        ]
    )
    db_session.commit()
    db_session.add_all(
        [
            BattleElfState(
                state_id="state_huoshen_self_damaged",
                battle_id="battle_self_damaged",
                side="self",
                elf_id="elf_huoshen",
                elf_name="火神",
                avatar="",
                panel_stats_json=dumps_json(
                    {
                        "hp": 410,
                        "physical_attack": 277,
                        "physical_defense": 163,
                        "magic_attack": 119,
                        "magic_defense": 139,
                        "speed": 229,
                    }
                ),
                current_hp_value=410,
                current_hp_percent=100,
                is_active_elf=True,
            ),
            BattleElfState(
                state_id="state_longxi_paer_self_damaged",
                battle_id="battle_self_damaged",
                side="enemy",
                elf_id="elf_longxi_paer",
                elf_name="龙息帕尔",
                avatar="",
                panel_stats_json=dumps_json(
                    {
                        "hp": 442,
                        "physical_attack": 270,
                        "physical_defense": 204,
                        "magic_attack": 116,
                        "magic_defense": 156,
                        "speed": 203,
                    }
                ),
                current_hp_value=442,
                current_hp_percent=100,
                is_active_elf=True,
            ),
        ]
    )
    db_session.commit()

    result = DamageEventService(db_session).create_damage_event(
        "battle_self_damaged",
        DamageEventCreate(
            turn_number=2,
            attacker_side="enemy",
            attacker_elf_id="elf_longxi_paer",
            defender_side="self",
            defender_elf_id="elf_huoshen",
            skill_id="skill_bat",
            skill_confirmed=True,
            damage_display_type=DamageDisplayType.SINGLE_DAMAGE,
            damage_value=121,
        ),
    )

    state = db_session.get(BattleElfState, "state_huoshen_self_damaged")
    assert result.damage_event.damage_value == 121
    assert state is not None
    assert state.current_hp_value == 289
    assert state.current_hp_percent == round(289 / 410 * 100, 4)
    resource_event = db_session.query(ResourceChangeEvent).filter_by(
        battle_id="battle_self_damaged",
        battle_event_id=result.battle_event.event_id,
    ).one()
    assert resource_event.value_type == "value"
    assert resource_event.value == 121
    assert resource_event.before_value == 410
    assert resource_event.after_value == 289


def test_damage_event_service_syncs_hp_percent_estimate_observation(
    db_session: Session,
) -> None:
    """敌方受击时，伤害数值和剩余 HP% 应在同一服务路径里约束实时估计。"""
    db_session.add_all(
        [
            Battle(
                battle_id="battle_hp_percent_filter",
                battle_name="HP 百分比实时估计",
                phase="battle",
                turn_number=1,
                self_active_elf_id="elf_attacker",
                enemy_active_elf_id="elf_enemy",
            ),
            ElfDefinition(
                elf_id="elf_attacker",
                elf_name="攻击方",
                avatar="",
                element_types_json=dumps_json(["fire"]),
                base_hp_talent=0,
                base_physical_attack_talent=0,
                base_physical_defense_talent=0,
                base_magic_attack_talent=0,
                base_magic_defense_talent=0,
                base_speed_talent=0,
            ),
            ElfDefinition(
                elf_id="elf_enemy",
                elf_name="敌方",
                avatar="",
                element_types_json=dumps_json(["normal"]),
                base_hp_talent=0,
                base_physical_attack_talent=0,
                base_physical_defense_talent=0,
                base_magic_attack_talent=0,
                base_magic_defense_talent=0,
                base_speed_talent=0,
            ),
            NatureDefinition(
                nature_id="nature_test",
                nature_name="测试性格",
                positive_stat="physical_attack",
                negative_stat="magic_attack",
            ),
            SkillDefinition(
                skill_id="skill_plain",
                skill_name="普通攻击",
                skill_icon=None,
                element_type="normal",
                skill_category="physical",
                base_power=50,
                base_energy_cost=0,
                priority_modifier=0,
            ),
        ]
    )
    db_session.commit()
    db_session.add_all(
        [
            BattleElfState(
                state_id="state_attacker",
                battle_id="battle_hp_percent_filter",
                side="self",
                elf_id="elf_attacker",
                elf_name="攻击方",
                avatar="",
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
                battle_id="battle_hp_percent_filter",
                side="enemy",
                elf_id="elf_enemy",
                elf_name="敌方",
                avatar="",
                panel_stats_json=dumps_json(
                    {
                        "hp": None,
                        "physical_attack": None,
                        "physical_defense": None,
                        "magic_attack": None,
                        "magic_defense": None,
                        "speed": None,
                    }
                ),
                current_hp_percent=100,
                is_active_elf=True,
            ),
        ]
    )
    db_session.commit()

    result = DamageEventService(db_session).create_damage_event(
        "battle_hp_percent_filter",
        DamageEventCreate(
            turn_number=1,
            attacker_side="self",
            attacker_elf_id="elf_attacker",
            defender_side="enemy",
            defender_elf_id="elf_enemy",
            skill_id="skill_plain",
            skill_confirmed=True,
            response_attack_success=False,
            response_defense_success=False,
            response_status_success=False,
            damage_display_type=DamageDisplayType.SINGLE_DAMAGE,
            damage_value=90,
            hp_percent_before=100,
            hp_percent_after=70,
        ),
    )

    observation_results = result.inference_result["estimate_observation_results"]
    assert [item["observation_type"] for item in observation_results] == [
        "damage_value",
        "hp_percent_delta",
    ]
    estimate = db_session.query(EnemyPanelEstimate).filter_by(
        battle_id="battle_hp_percent_filter",
        elf_id="elf_enemy",
    ).one()
    constraints = loads_json(estimate.stat_constraints_json, {})
    assert constraints["hp"]["integer_min"] == 300
    assert constraints["hp"]["integer_max"] == 310


def test_damage_event_service_reverses_paer_attack_after_strength_boost(
    db_session: Session,
) -> None:
    """龙息帕尔力量增效后用蝙蝠攻击火神，应反推回未增益物攻面板。"""
    db_session.add_all(
        [
            Battle(
                battle_id="battle_paer_strength",
                battle_name="力量增效真实样例",
                phase="battle",
                turn_number=2,
                self_active_elf_id="elf_huoshen",
                enemy_active_elf_id="elf_longxi_paer",
            ),
            ElfDefinition(
                elf_id="elf_huoshen",
                elf_name="火神",
                avatar="",
                element_types_json=dumps_json(["fire"]),
                base_hp_talent=117,
                base_physical_attack_talent=139,
                base_physical_defense_talent=94,
                base_magic_attack_talent=61,
                base_magic_defense_talent=72,
                base_speed_talent=130,
            ),
            ElfDefinition(
                elf_id="elf_longxi_paer",
                elf_name="龙息帕尔",
                avatar="",
                element_types_json=dumps_json(["dark"]),
                base_hp_talent=130,
                base_physical_attack_talent=127,
                base_physical_defense_talent=131,
                base_magic_attack_talent=57,
                base_magic_defense_talent=87,
                base_speed_talent=100,
            ),
            SkillDefinition(
                skill_id="skill_bat",
                skill_name="蝙蝠",
                skill_icon=None,
                element_type="dark",
                skill_category="physical",
                base_power=65,
                base_energy_cost=2,
                priority_modifier=0,
            ),
            EffectDefinition(
                effect_id="effect_physical_attack_up_layered",
                effect_name="物攻增加",
                category="stat_modifier",
                polarity="positive",
                display_group="stat_modifier",
                display_priority=400,
                owner_scope="elf",
                target_scope="single_elf",
                attach_target_type="elf",
                default_layers=1,
                max_layers=None,
                stack_rule="add_layers",
                duration_type="until_removed",
                clear_on_switch=True,
                stat_modifier_json=dumps_json(
                    {
                        "modifier_type": "stat_stage",
                        "modifiers": [
                            {
                                "modifier_type": "stat_stage",
                                "stat": "physical_attack",
                                "value_type": "percent_add",
                                "value_per_layer": 0.1,
                            }
                        ],
                    }
                ),
                formula_hooks_json=dumps_json(["stat_stage_attack_up"]),
            ),
            NatureDefinition(
                nature_id="physical_attack_plus_magic_attack_minus",
                nature_name="加物攻减魔攻",
                positive_stat="physical_attack",
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
    db_session.commit()
    db_session.add_all(
        [
            BattleElfState(
                state_id="state_huoshen_strength",
                battle_id="battle_paer_strength",
                side="self",
                elf_id="elf_huoshen",
                elf_name="火神",
                avatar="",
                panel_stats_json=dumps_json(
                    {
                        "hp": 410,
                        "physical_attack": 277,
                        "physical_defense": 163,
                        "magic_attack": 119,
                        "magic_defense": 139,
                        "speed": 229,
                    }
                ),
                current_hp_value=410,
                current_hp_percent=100,
                is_active_elf=True,
            ),
            BattleElfState(
                state_id="state_longxi_paer_strength",
                battle_id="battle_paer_strength",
                side="enemy",
                elf_id="elf_longxi_paer",
                elf_name="龙息帕尔",
                avatar="",
                panel_stats_json=dumps_json(
                    {
                        "hp": None,
                        "physical_attack": None,
                        "physical_defense": None,
                        "magic_attack": None,
                        "magic_defense": None,
                        "speed": None,
                    }
                ),
                current_hp_percent=100,
                is_active_elf=True,
            ),
            BattleEffectInstance(
                instance_id="strength_up_paer",
                battle_id="battle_paer_strength",
                effect_id="effect_physical_attack_up_layered",
                category="stat_modifier",
                owner_scope="elf",
                owner_side="enemy",
                owner_elf_id="elf_longxi_paer",
                layers=10,
                is_active=True,
                applied_turn=1,
                manual_override=True,
            ),
        ]
    )
    db_session.commit()

    result = DamageEventService(db_session).create_damage_event(
        "battle_paer_strength",
        DamageEventCreate(
            turn_number=2,
            attacker_side="enemy",
            attacker_elf_id="elf_longxi_paer",
            defender_side="self",
            defender_elf_id="elf_huoshen",
            skill_id="skill_bat",
            skill_confirmed=True,
            damage_display_type=DamageDisplayType.SINGLE_DAMAGE,
            damage_value=242,
        ),
    )

    assert result.inference_result["status"] == "formula_unavailable"
    assert result.inference_result["estimate_updated"] is True
    formula_context = loads_json(result.damage_event.formula_context_json, {})
    assert float(formula_context["stat_stage_multiplier"]) == 2.0
    assert formula_context["rule_resolution_details"]["stat_stage_multiplier"]["items"][0][
        "effect_id"
    ] == "effect_physical_attack_up_layered"

    estimate = db_session.query(EnemyPanelEstimate).filter_by(
        battle_id="battle_paer_strength",
        elf_id="elf_longxi_paer",
    ).one()
    constraints = loads_json(estimate.stat_constraints_json, {})
    physical_attack = constraints["physical_attack"]
    assert physical_attack["integer_min"] == 269
    assert physical_attack["integer_max"] == 270
    assert physical_attack["relation"] == "offense_range_from_known_defense"
    assert estimate.default_panel_json is not None
    default_panel = loads_json(estimate.default_panel_json, {})
    assert default_panel["physical_attack"] == 270
