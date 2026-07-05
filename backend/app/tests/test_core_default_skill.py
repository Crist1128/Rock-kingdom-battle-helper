"""核心默认技能与战斗初始资源测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.calculation.formula_context import DamageFormulaContext
from app.core.default_skills import DEFAULT_COMMON_SKILL_ID, DEFAULT_INITIAL_ENERGY
from app.core.enums import BattleEventType, BattlePhase, DamageDisplayType
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState, BattleSkillSlot
from app.models.effect import BattleEffectInstance
from app.models.event import BattleEvent, ResourceChangeEvent
from app.models.static import (
    EffectDefinition,
    ElfDefinition,
    NatureDefinition,
    PlayerElfBuild,
    PlayerElfBuildSkill,
    SkillDefinition,
)
from app.schemas.battle import LineupInput, RuntimeFormChangeInput, SwitchElfInput
from app.schemas.event import BattleEventCreate, DamageEventCreate
from app.seed.core_skills import ensure_core_skills
from app.services.battle_service import BattleService
from app.services.damage_event_service import DamageEventService
from app.services.effect_operation_executor import EffectOperationExecutor
from app.services.turn_settlement_service import TurnSettlementService
from app.utils.json import dumps_json, loads_json


@pytest.fixture()
def session_factory() -> Iterator[sessionmaker[Session]]:
    """创建隔离内存数据库。"""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_setup_lineup_initializes_energy_and_common_skill(
    session_factory: sessionmaker[Session],
) -> None:
    """录入阵容时双方精灵初始能量为 10，并拥有默认通用技能。"""
    with session_factory() as session:
        _seed_static_rules(session)
        ensure_core_skills(session)
        session.flush()
        session.add(Battle(battle_id="battle_defaults", phase=BattlePhase.PREPARATION.value))
        session.add(
            PlayerElfBuild(
                build_id="build_self",
                elf_id="elf_self",
                nature_id="nature_test",
                individual_talent_distribution_json=dumps_json({}),
                final_stats_json=dumps_json(
                    {
                        "hp": 500,
                        "physical_attack": 100,
                        "physical_defense": 100,
                        "magic_attack": 100,
                        "magic_defense": 100,
                        "speed": 100,
                    }
                ),
            )
        )
        session.flush()
        session.add(
            PlayerElfBuildSkill(
                build_id="build_self",
                slot_index=0,
                skill_id="skill_attack",
            )
        )
        session.commit()

        BattleService(session).setup_lineup(
            "battle_defaults",
            LineupInput(
                elves=[
                    {
                        "side": "self",
                        "elf_id": "elf_self",
                        "build_id": "build_self",
                        "is_active_elf": True,
                    },
                    {"side": "enemy", "elf_id": "elf_enemy", "is_active_elf": True},
                ]
            ),
        )

        states = list(
            session.scalars(
                select(BattleElfState)
                .where(BattleElfState.battle_id == "battle_defaults")
                .order_by(BattleElfState.side)
            ).all()
        )
        assert {state.energy for state in states} == {DEFAULT_INITIAL_ENERGY}
        for state in states:
            assert DEFAULT_COMMON_SKILL_ID in loads_json(state.skill_ids_json, [])

        self_state = next(state for state in states if state.side == "self")
        assert DEFAULT_COMMON_SKILL_ID in loads_json(self_state.confirmed_skill_ids_json, [])


def test_skill_runtime_supports_missing_hp_dynamic_energy_cost(
    session_factory: sessionmaker[Session],
) -> None:
    """Dynamic energy cost can be reduced by the actor's missing HP percent."""
    with session_factory() as session:
        _seed_static_rules(session)
        session.flush()
        session.add(
            SkillDefinition(
                skill_id="skill_missing_hp_cost",
                skill_name="missing hp cost",
                element_type="普通",
                skill_category="physical",
                base_power=50,
                base_energy_cost=8,
                priority_modifier=0,
                damage_rule_json=dumps_json(
                    {
                        "dynamic_energy_cost_rule": {
                            "missing_hp_percent_step": 10,
                            "energy_cost_delta_per_step": -1,
                        }
                    }
                ),
            )
        )
        session.add(
            Battle(
                battle_id="battle_missing_hp_cost",
                phase=BattlePhase.BATTLE.value,
                turn_number=1,
                self_active_elf_id="elf_self",
            )
        )
        session.flush()
        state = _elf_state("battle_missing_hp_cost", "self", "elf_self", energy=20)
        state.current_hp_value = 300
        state.current_hp_percent = 60.0
        session.add(state)
        event = BattleEvent(
            event_id="event_missing_hp_cost",
            battle_id="battle_missing_hp_cost",
            turn_number=1,
            event_type=BattleEventType.SKILL_USE.value,
            actor_side="self",
            actor_elf_id="elf_self",
            skill_id="skill_missing_hp_cost",
            skill_confirmed=True,
            payload_json=dumps_json({}),
        )
        session.add(event)
        session.commit()

        result = BattleService(session)._process_skill_runtime(event)

        assert result is not None
        assert result["effective_energy_cost"] == 4
        session.flush()
        session.refresh(state)
        assert state.energy == 16


def test_other_element_skill_use_can_add_listener_skill_power(
    session_factory: sessionmaker[Session],
) -> None:
    """Using another skill of the configured element can persistently add listener power."""
    with session_factory() as session:
        _seed_static_rules(session)
        session.flush()
        session.add_all(
            [
                SkillDefinition(
                    skill_id="skill_listener",
                    skill_name="listener",
                    element_type="light",
                    skill_category="magic",
                    base_power=40,
                    base_energy_cost=0,
                    priority_modifier=0,
                    damage_rule_json=dumps_json(
                        {
                            "manual_review": {
                                "future_hooks": [
                                    {
                                        "hook_type": "persistent_skill_power_modifier",
                                        "target": "source_skill",
                                        "power_add": 60,
                                        "trigger": "other_element_skill_use",
                                        "element_type": "草",
                                        "status": "executable",
                                    }
                                ]
                            }
                        }
                    ),
                ),
                SkillDefinition(
                    skill_id="skill_grass_used",
                    skill_name="grass used",
                    element_type="grass",
                    skill_category="magic",
                    base_power=30,
                    base_energy_cost=0,
                    priority_modifier=0,
                ),
                Battle(
                    battle_id="battle_other_element",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=1,
                    self_active_elf_id="elf_self",
                ),
                _elf_state("battle_other_element", "self", "elf_self", energy=20),
            ]
        )
        session.flush()
        session.add_all(
            [
                BattleSkillSlot(
                    slot_id="slot_listener",
                    battle_id="battle_other_element",
                    side="self",
                    elf_id="elf_self",
                    slot_index=0,
                    skill_id="skill_listener",
                    active_effect_instance_ids_json=dumps_json([]),
                    manual_override=False,
                ),
            ]
        )
        event = BattleEvent(
            event_id="event_grass_used",
            battle_id="battle_other_element",
            turn_number=1,
            event_type=BattleEventType.SKILL_USE.value,
            actor_side="self",
            actor_elf_id="elf_self",
            skill_id="skill_grass_used",
            skill_confirmed=True,
            payload_json=dumps_json({}),
        )
        session.add(event)
        session.commit()

        result = BattleService(session)._process_skill_runtime(event)

        assert result is not None
        assert result["other_skill_use_listener_results"][0]["power_add"] == 60
        slot = session.get(BattleSkillSlot, "slot_listener")
        assert slot is not None
        assert slot.current_power == 100


def test_response_success_listener_reduces_skill_cost_until_used(
    session_factory: sessionmaker[Session],
) -> None:
    """A response-success listener can reduce its own slot cost and reset after use."""
    with session_factory() as session:
        _seed_static_rules(session)
        session.flush()
        session.add_all(
            [
                SkillDefinition(
                    skill_id="skill_qichen",
                    skill_name="qichen",
                    element_type="普通",
                    skill_category="status",
                    base_power=None,
                    base_energy_cost=10,
                    priority_modifier=0,
                    damage_rule_json=dumps_json(
                        {
                            "manual_review": {
                                "future_hooks": [
                                    {
                                        "hook_type": "response_success_skill_cost_listener",
                                        "target": "source_skill",
                                        "cost_delta": -3,
                                        "trigger": "any_response_success",
                                        "status": "executable",
                                    },
                                    {
                                        "hook_type": "reset_skill_cost_modifier",
                                        "target": "source_skill",
                                        "trigger": "after_skill_use",
                                        "status": "executable",
                                    },
                                ]
                            }
                        }
                    ),
                ),
                SkillDefinition(
                    skill_id="skill_response",
                    skill_name="response",
                    element_type="普通",
                    skill_category="status",
                    base_power=None,
                    base_energy_cost=0,
                    priority_modifier=0,
                ),
                Battle(
                    battle_id="battle_response_listener",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=1,
                    self_active_elf_id="elf_self",
                ),
                _elf_state("battle_response_listener", "self", "elf_self", energy=30),
            ]
        )
        session.flush()
        session.add_all(
            [
                BattleSkillSlot(
                    slot_id="slot_qichen",
                    battle_id="battle_response_listener",
                    side="self",
                    elf_id="elf_self",
                    slot_index=0,
                    skill_id="skill_qichen",
                    active_effect_instance_ids_json=dumps_json([]),
                    manual_override=False,
                ),
            ]
        )
        response_event = BattleEvent(
            event_id="event_response_success",
            battle_id="battle_response_listener",
            turn_number=1,
            event_type=BattleEventType.SKILL_USE.value,
            actor_side="self",
            actor_elf_id="elf_self",
            skill_id="skill_response",
            skill_confirmed=True,
            payload_json=dumps_json(
                {"condition_flags": {"response_attack_success": True}}
            ),
        )
        session.add(response_event)
        session.commit()

        BattleService(session)._process_skill_runtime(response_event)
        slot = session.get(BattleSkillSlot, "slot_qichen")
        assert slot is not None
        assert slot.current_energy_cost == 7

        use_event = BattleEvent(
            event_id="event_qichen_use",
            battle_id="battle_response_listener",
            turn_number=2,
            event_type=BattleEventType.SKILL_USE.value,
            actor_side="self",
            actor_elf_id="elf_self",
            skill_id="skill_qichen",
            skill_confirmed=True,
            payload_json=dumps_json({}),
        )
        session.add(use_event)
        session.flush()
        result = BattleService(session)._process_skill_runtime(use_event)

        assert result is not None
        assert result["base_runtime_energy_cost"] == 7
        assert slot.current_energy_cost == 10


def test_effect_operation_can_target_enemy_current_turn_used_skill_slot(
    session_factory: sessionmaker[Session],
) -> None:
    """Effect operations can attach a skill-slot modifier to the opponent's used skill."""
    with session_factory() as session:
        _seed_static_rules(session)
        session.flush()
        session.add(
            EffectDefinition(
                effect_id="effect_slot_cost_up",
                effect_name="slot cost up",
                category="skill_modifier",
                polarity="negative",
                display_group="skill_modifier",
                display_priority=1,
                owner_scope="skill_slot",
                target_scope="single_skill_slot",
                attach_target_type="skill_slot",
                default_layers=1,
                max_layers=1,
                stack_rule="refresh",
                duration_type="turns",
                default_duration_turns=3,
                skill_modifier_json=dumps_json(
                    {"modifier_type": "skill_energy_cost_delta", "energy_cost_delta": 7}
                ),
            )
        )
        session.add(
            Battle(
                battle_id="battle_control",
                phase=BattlePhase.BATTLE.value,
                turn_number=1,
                self_active_elf_id="elf_self",
                enemy_active_elf_id="elf_enemy",
            )
        )
        session.flush()
        session.add_all(
            [
                BattleSkillSlot(
                    slot_id="slot_enemy_used",
                    battle_id="battle_control",
                    side="enemy",
                    elf_id="elf_enemy",
                    slot_index=0,
                    skill_id="skill_attack",
                    active_effect_instance_ids_json=dumps_json([]),
                    manual_override=False,
                ),
                BattleEvent(
                    event_id="event_enemy_used",
                    battle_id="battle_control",
                    turn_number=1,
                    action_order=1,
                    event_type=BattleEventType.SKILL_USE.value,
                    actor_side="enemy",
                    actor_elf_id="elf_enemy",
                    skill_id="skill_attack",
                    skill_confirmed=True,
                    payload_json=dumps_json({}),
                ),
            ]
        )
        control_event = BattleEvent(
            event_id="event_control",
            battle_id="battle_control",
            turn_number=1,
            action_order=2,
            event_type=BattleEventType.SKILL_USE.value,
            actor_side="self",
            actor_elf_id="elf_self",
            target_side="enemy",
            target_elf_id="elf_enemy",
            skill_id="skill_attack",
            skill_confirmed=True,
            payload_json=dumps_json({}),
        )
        session.add(control_event)
        session.commit()

        results = EffectOperationExecutor(session).execute_operations_for_event(
            control_event,
            [
                {
                    "op_type": "apply_effect",
                    "effect_id": "effect_slot_cost_up",
                    "target": "enemy_current_turn_used_skill",
                    "layers": 1,
                    "condition": "always",
                }
            ],
        )

        assert results[0]["status"] == "executed"
        instance = session.scalar(
            select(BattleEffectInstance).where(
                BattleEffectInstance.effect_id == "effect_slot_cost_up"
            )
        )
        assert instance is not None
        assert instance.owner_scope == "skill_slot"
        assert instance.owner_skill_slot_id == "slot_enemy_used"


def test_damage_event_triggers_after_use_power_modifier(
    session_factory: sessionmaker[Session],
) -> None:
    """录入攻击伤害后，应执行“使用后本技能威力增加”的技能槽钩子。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add(
            SkillDefinition(
                skill_id="skill_blow_fire",
                skill_name="吹火",
                element_type="火",
                skill_category="physical",
                base_power=50,
                base_energy_cost=1,
                priority_modifier=0,
                damage_rule_json=dumps_json(
                    {
                        "manual_review": {
                            "future_hooks": [
                                {
                                    "status": "executable",
                                    "hook_type": "persistent_skill_power_modifier",
                                    "trigger": "after_skill_use",
                                    "target": "source_skill",
                                    "power_add": 20,
                                }
                            ]
                        }
                    }
                ),
            )
        )
        session.add(
            Battle(
                battle_id="battle_blow_fire",
                phase=BattlePhase.BATTLE.value,
                turn_number=1,
                self_active_elf_id="elf_self",
                enemy_active_elf_id="elf_enemy",
            )
        )
        session.flush()
        session.add_all(
            [
                _elf_state("battle_blow_fire", "self", "elf_self", energy=10),
                _elf_state("battle_blow_fire", "enemy", "elf_enemy", energy=10),
            ]
        )
        session.commit()

        DamageEventService(session).create_damage_event(
            "battle_blow_fire",
            DamageEventCreate(
                attacker_side="self",
                attacker_elf_id="elf_self",
                defender_side="enemy",
                defender_elf_id="elf_enemy",
                skill_id="skill_blow_fire",
                skill_confirmed=True,
                damage_display_type=DamageDisplayType.SINGLE_DAMAGE,
                damage_value=10,
                sync_observation=False,
            ),
        )

        slot = session.scalar(
            select(BattleSkillSlot).where(
                BattleSkillSlot.battle_id == "battle_blow_fire",
                BattleSkillSlot.skill_id == "skill_blow_fire",
            )
        )
        assert slot is not None
        assert slot.current_power == 70


def test_damage_event_triggers_other_fire_skill_power_multiplier(
    session_factory: sessionmaker[Session],
) -> None:
    """录入其他火系攻击伤害后，山火应按当前精灵自己的技能槽永久翻倍。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                SkillDefinition(
                    skill_id="skill_mountain_fire",
                    skill_name="山火",
                    element_type="fire",
                    skill_category="physical",
                    base_power=15,
                    base_energy_cost=3,
                    priority_modifier=0,
                    damage_rule_json=dumps_json(
                        {
                            "manual_review": {
                                "future_hooks": [
                                    {
                                        "status": "executable",
                                        "hook_type": "persistent_skill_power_modifier",
                                        "trigger": "other_element_skill_use",
                                        "element_type": "火",
                                        "target": "source_skill",
                                        "power_multiplier": 2,
                                    }
                                ]
                            }
                        }
                    ),
                ),
                SkillDefinition(
                    skill_id="skill_other_fire",
                    skill_name="其他火系",
                    element_type="fire",
                    skill_category="physical",
                    base_power=30,
                    base_energy_cost=1,
                    priority_modifier=0,
                ),
            ]
        )
        session.add(
            Battle(
                battle_id="battle_mountain_fire",
                phase=BattlePhase.BATTLE.value,
                turn_number=1,
                self_active_elf_id="elf_self",
                enemy_active_elf_id="elf_enemy",
            )
        )
        session.flush()
        session.add_all(
            [
                _elf_state("battle_mountain_fire", "self", "elf_self", energy=10),
                _elf_state("battle_mountain_fire", "enemy", "elf_enemy", energy=10),
                BattleSkillSlot(
                    slot_id="slot_mountain_fire",
                    battle_id="battle_mountain_fire",
                    side="self",
                    elf_id="elf_self",
                    slot_index=0,
                    skill_id="skill_mountain_fire",
                    active_effect_instance_ids_json=dumps_json([]),
                    manual_override=False,
                ),
            ]
        )
        session.commit()

        DamageEventService(session).create_damage_event(
            "battle_mountain_fire",
            DamageEventCreate(
                attacker_side="self",
                attacker_elf_id="elf_self",
                defender_side="enemy",
                defender_elf_id="elf_enemy",
                skill_id="skill_other_fire",
                skill_confirmed=True,
                damage_display_type=DamageDisplayType.SINGLE_DAMAGE,
                damage_value=10,
                sync_observation=False,
            ),
        )

        slot = session.get(BattleSkillSlot, "slot_mountain_fire")
        assert slot is not None
        assert slot.current_power == 30


def test_battle_state_enriches_carried_skill_slots_with_power_preview(
    session_factory: sessionmaker[Session],
) -> None:
    """Battle state should expose carried slots and current-state power preview."""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add(
            ElfDefinition(
                elf_id="elf_enemy_bench",
                elf_name="bench enemy",
                avatar="",
                element_types_json=dumps_json(["normal"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            )
        )
        for index in range(2, 5):
            session.add(
                SkillDefinition(
                    skill_id=f"skill_attack_{index}",
                    skill_name=f"attack {index}",
                    element_type="normal",
                    skill_category="physical",
                    base_power=40 + index,
                    base_energy_cost=index,
                    priority_modifier=0,
                )
            )
        session.add(
            EffectDefinition(
                effect_id="effect_test_physical_attack_up",
                effect_name="physical attack up",
                category="stat_modifier",
                polarity="positive",
                display_group="stat_modifier",
                display_priority=1,
                owner_scope="elf",
                target_scope="single_elf",
                attach_target_type="elf",
                default_layers=1,
                stack_rule="replace",
                duration_type="until_removed",
                clear_on_switch=True,
                stat_modifier_json=dumps_json(
                    {
                        "modifier_type": "stat_stage",
                        "stat": "physical_attack",
                        "value_type": "percent_add",
                        "value": 1.0,
                    }
                ),
            )
        )
        session.add(Battle(battle_id="battle_slot_preview", phase=BattlePhase.PREPARATION.value))
        session.add(
            PlayerElfBuild(
                build_id="build_slot_preview",
                elf_id="elf_self",
                nature_id="nature_test",
                individual_talent_distribution_json=dumps_json({}),
                final_stats_json=dumps_json(
                    {
                        "hp": 500,
                        "physical_attack": 100,
                        "physical_defense": 100,
                        "magic_attack": 100,
                        "magic_defense": 100,
                        "speed": 100,
                    }
                ),
            )
        )
        session.flush()
        for slot_index, skill_id in enumerate(
            ["skill_attack", "skill_attack_2", "skill_attack_3", "skill_attack_4"]
        ):
            session.add(
                PlayerElfBuildSkill(
                    build_id="build_slot_preview",
                    slot_index=slot_index,
                    skill_id=skill_id,
                )
            )
        session.commit()

        service = BattleService(session)
        service.setup_lineup(
            "battle_slot_preview",
            LineupInput(
                elves=[
                    {
                        "side": "self",
                        "elf_id": "elf_self",
                        "build_id": "build_slot_preview",
                        "is_active_elf": True,
                    },
                    {"side": "enemy", "elf_id": "elf_enemy", "is_active_elf": True},
                    {"side": "enemy", "elf_id": "elf_enemy_bench", "is_active_elf": False},
                ]
            ),
        )
        enemy_states = list(
            session.scalars(
                select(BattleElfState).where(
                    BattleElfState.battle_id == "battle_slot_preview",
                    BattleElfState.side == "enemy",
                )
            ).all()
        )
        assert len(enemy_states) == 2
        for enemy_state in enemy_states:
            enemy_state.panel_stats_json = dumps_json(
                {
                    "hp": 500,
                    "physical_attack": 100,
                    "physical_defense": 100,
                    "magic_attack": 100,
                    "magic_defense": 100,
                    "speed": 100,
                }
            )
            enemy_state.current_hp_value = 500
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_slot_preview",
                battle_id="battle_slot_preview",
                effect_id="effect_test_physical_attack_up",
                category="stat_modifier",
                owner_scope="elf",
                owner_side="self",
                owner_elf_id="elf_self",
                layers=1,
                is_active=True,
            )
        )
        session.commit()

        battle = session.get(Battle, "battle_slot_preview")
        assert battle is not None
        state = service.get_state(battle)
        self_state = next(
            item for item in state.elves
            if item["side"] == "self" and item["elf_id"] == "elf_self"
        )
        assert self_state["nature_id"] == "nature_test"
        assert self_state["nature_source"] == "runtime_state"
        self_slots = [
            item for item in state.skill_slots
            if item["side"] == "self" and item["elf_id"] == "elf_self"
        ]
        assert len(self_slots) == 4
        assert [item["slot_index"] for item in self_slots] == [0, 1, 2, 3]
        assert {item["skill_id"] for item in self_slots} == {
            "skill_attack",
            "skill_attack_2",
            "skill_attack_3",
            "skill_attack_4",
        }
        first_slot = self_slots[0]
        assert first_slot["skill_name"] == "测试攻击"
        assert first_slot["static_base_power"] == 50
        assert first_slot["effective_energy_cost"] == 0
        assert first_slot["power_preview"]["multipliers"]["stab"] == "1.25"
        assert first_slot["power_preview"]["multipliers"]["stat_stage"] == "2"
        assert first_slot["power_preview"]["effective_display_power"] == 125
        damage_preview = first_slot["damage_preview"]
        assert damage_preview["status"] == "resolved"
        assert len(damage_preview["targets"]) == 2
        assert damage_preview["current_target"]["elf_id"] == "elf_enemy"
        assert damage_preview["current_target"]["damage_value"] == 112
        assert damage_preview["current_target"]["damage_percent"] == 22.4

        damage_result = DamageEventService(session).create_damage_event(
            "battle_slot_preview",
            DamageEventCreate(
                turn_number=1,
                attacker_side="enemy",
                attacker_elf_id="elf_enemy",
                defender_side="self",
                defender_elf_id="elf_self",
                skill_id="skill_attack",
                skill_confirmed=True,
                damage_display_type=DamageDisplayType.SINGLE_DAMAGE,
                damage_value=56,
                sync_observation=False,
            ),
        )
        event_payload = loads_json(damage_result.battle_event.payload_json, {})
        assert event_payload["skill_runtime"]["record_source"] == "damage_event"
        assert event_payload["skill_runtime"]["slot_created"] is True

        battle = session.get(Battle, "battle_slot_preview")
        assert battle is not None
        state_after_enemy_damage = service.get_state(battle)
        enemy_slots = [
            item for item in state_after_enemy_damage.skill_slots
            if item["side"] == "enemy" and item["elf_id"] == "elf_enemy"
        ]
        assert len(enemy_slots) == 1
        assert enemy_slots[0]["skill_id"] == "skill_attack"
        enemy_damage_preview = enemy_slots[0]["damage_preview"]
        assert enemy_damage_preview["status"] == "resolved"
        assert enemy_damage_preview["current_target"]["elf_id"] == "elf_self"
        assert enemy_damage_preview["current_target"]["status"] == "calculated"
        assert enemy_damage_preview["current_target"]["damage_value"] > 0


def test_common_focus_skill_gains_energy(session_factory: sessionmaker[Session]) -> None:
    """使用聚能时，结构化操作给行动方增加 5 点能量。"""
    with session_factory() as session:
        _seed_static_rules(session)
        ensure_core_skills(session)
        session.flush()
        session.add(
            Battle(
                battle_id="battle_focus",
                phase=BattlePhase.BATTLE.value,
                turn_number=1,
                self_active_elf_id="elf_self",
                enemy_active_elf_id="elf_enemy",
            )
        )
        session.flush()
        session.add(_elf_state("battle_focus", "self", "elf_self", energy=DEFAULT_INITIAL_ENERGY))
        session.add(_elf_state("battle_focus", "enemy", "elf_enemy", energy=DEFAULT_INITIAL_ENERGY))
        session.commit()

        BattleService(session).create_event(
            "battle_focus",
            BattleEventCreate(
                turn_number=1,
                event_type=BattleEventType.SKILL_USE.value,
                actor_side="self",
                actor_elf_id="elf_self",
                target_side="enemy",
                target_elf_id="elf_enemy",
                skill_id=DEFAULT_COMMON_SKILL_ID,
                skill_confirmed=True,
                manual_override=True,
            ),
        )

        state = session.scalar(
            select(BattleElfState).where(
                BattleElfState.battle_id == "battle_focus",
                BattleElfState.side == "self",
                BattleElfState.elf_id == "elf_self",
            )
        )
        assert state is not None
        assert state.energy == DEFAULT_INITIAL_ENERGY + 5

        resource_event = session.scalar(
            select(ResourceChangeEvent).where(ResourceChangeEvent.battle_id == "battle_focus")
        )
        assert resource_event is not None
        assert resource_event.resource_type == "energy"
        assert resource_event.change_type == "gain"
        assert resource_event.before_value == DEFAULT_INITIAL_ENERGY
        assert resource_event.after_value == DEFAULT_INITIAL_ENERGY + 5


def test_skill_use_consumes_base_energy_cost(
    session_factory: sessionmaker[Session],
) -> None:
    """使用普通技能时应按 SkillDefinition.base_energy_cost 扣除行动方能量。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add(
            SkillDefinition(
                skill_id="skill_cost_3",
                skill_name="测试耗能技能",
                element_type="normal",
                skill_category="physical",
                base_power=50,
                base_energy_cost=3,
                priority_modifier=0,
            )
        )
        session.add(
            Battle(
                battle_id="battle_cost",
                phase=BattlePhase.BATTLE.value,
                turn_number=1,
                self_active_elf_id="elf_self",
                enemy_active_elf_id="elf_enemy",
            )
        )
        session.flush()
        session.add(_elf_state("battle_cost", "self", "elf_self", energy=DEFAULT_INITIAL_ENERGY))
        session.add(_elf_state("battle_cost", "enemy", "elf_enemy", energy=DEFAULT_INITIAL_ENERGY))
        session.commit()

        BattleService(session).create_event(
            "battle_cost",
            BattleEventCreate(
                turn_number=1,
                event_type=BattleEventType.SKILL_USE.value,
                actor_side="self",
                actor_elf_id="elf_self",
                target_side="enemy",
                target_elf_id="elf_enemy",
                skill_id="skill_cost_3",
                skill_confirmed=True,
                manual_override=True,
            ),
        )

        state = session.scalar(
            select(BattleElfState).where(
                BattleElfState.battle_id == "battle_cost",
                BattleElfState.side == "self",
                BattleElfState.elf_id == "elf_self",
            )
        )
        assert state is not None
        assert state.energy == DEFAULT_INITIAL_ENERGY - 3

        resource_event = session.scalar(
            select(ResourceChangeEvent).where(ResourceChangeEvent.battle_id == "battle_cost")
        )
        assert resource_event is not None
        assert resource_event.resource_type == "energy"
        assert resource_event.change_type == "consume"
        assert resource_event.value == 3
        assert resource_event.before_value == DEFAULT_INITIAL_ENERGY
        assert resource_event.after_value == DEFAULT_INITIAL_ENERGY - 3


def test_skill_use_consumes_runtime_skill_slot_energy_cost(
    session_factory: sessionmaker[Session],
) -> None:
    """Runtime skill slot cost should override SkillDefinition.base_energy_cost."""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add(
            SkillDefinition(
                skill_id="skill_cost_runtime",
                skill_name="runtime cost skill",
                element_type="normal",
                skill_category="physical",
                base_power=50,
                base_energy_cost=3,
                priority_modifier=0,
            )
        )
        session.add(
            Battle(
                battle_id="battle_runtime_cost",
                phase=BattlePhase.BATTLE.value,
                turn_number=1,
                self_active_elf_id="elf_self",
                enemy_active_elf_id="elf_enemy",
            )
        )
        session.flush()
        session.add(
            _elf_state("battle_runtime_cost", "self", "elf_self", energy=DEFAULT_INITIAL_ENERGY)
        )
        session.add(
            _elf_state("battle_runtime_cost", "enemy", "elf_enemy", energy=DEFAULT_INITIAL_ENERGY)
        )
        session.add(
            BattleSkillSlot(
                slot_id="runtime_slot_cost",
                battle_id="battle_runtime_cost",
                side="self",
                elf_id="elf_self",
                slot_index=0,
                skill_id="skill_cost_runtime",
                current_energy_cost=1,
                active_effect_instance_ids_json=dumps_json([]),
            )
        )
        session.commit()

        event = BattleService(session).create_event(
            "battle_runtime_cost",
            BattleEventCreate(
                turn_number=1,
                event_type=BattleEventType.SKILL_USE.value,
                actor_side="self",
                actor_elf_id="elf_self",
                target_side="enemy",
                target_elf_id="elf_enemy",
                skill_id="skill_cost_runtime",
                skill_confirmed=True,
                manual_override=True,
            ),
        )

        state = session.scalar(
            select(BattleElfState).where(
                BattleElfState.battle_id == "battle_runtime_cost",
                BattleElfState.side == "self",
                BattleElfState.elf_id == "elf_self",
            )
        )
        assert state is not None
        assert state.energy == DEFAULT_INITIAL_ENERGY - 1

        payload = loads_json(event.payload_json, {})
        assert payload["skill_runtime"]["static_energy_cost"] == 3
        assert payload["skill_runtime"]["effective_energy_cost"] == 1


def test_side_skill_modifier_mark_changes_runtime_energy_cost(
    session_factory: sessionmaker[Session],
) -> None:
    """Side-scope skill modifier marks should affect skill runtime cost."""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                SkillDefinition(
                    skill_id="skill_cost_marked",
                    skill_name="marked cost skill",
                    element_type="normal",
                    skill_category="physical",
                    base_power=50,
                    base_energy_cost=3,
                    priority_modifier=0,
                ),
                EffectDefinition(
                    effect_id="effect_wet_mark",
                    effect_name="wet mark",
                    category="mark",
                    polarity="positive",
                    display_group="mark",
                    display_priority=1,
                    owner_scope="side",
                    target_scope="side",
                    attach_target_type="side",
                    skill_modifier_json=dumps_json(
                        {
                            "modifier_type": "energy_cost_delta",
                            "energy_cost_delta_per_layer": -1,
                        }
                    ),
                ),
                Battle(
                    battle_id="battle_mark_cost",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=1,
                    self_active_elf_id="elf_self",
                    enemy_active_elf_id="elf_enemy",
                ),
            ]
        )
        session.flush()
        session.add(_elf_state("battle_mark_cost", "self", "elf_self", energy=10))
        session.add(_elf_state("battle_mark_cost", "enemy", "elf_enemy", energy=10))
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_wet",
                battle_id="battle_mark_cost",
                effect_id="effect_wet_mark",
                category="mark",
                owner_scope="side",
                owner_side="self",
                layers=2,
                is_active=True,
                applied_turn=1,
            )
        )
        session.commit()

        event = BattleService(session).create_event(
            "battle_mark_cost",
            BattleEventCreate(
                turn_number=1,
                event_type=BattleEventType.SKILL_USE.value,
                actor_side="self",
                actor_elf_id="elf_self",
                target_side="enemy",
                target_elf_id="elf_enemy",
                skill_id="skill_cost_marked",
                skill_confirmed=True,
                manual_override=True,
            ),
        )

        state = session.scalar(
            select(BattleElfState).where(
                BattleElfState.battle_id == "battle_mark_cost",
                BattleElfState.side == "self",
                BattleElfState.elf_id == "elf_self",
            )
        )
        assert state is not None
        assert state.energy == 9
        payload = loads_json(event.payload_json, {})
        assert payload["skill_runtime"]["effective_energy_cost"] == 1


def test_one_use_cost_modifier_is_consumed_after_skill_use(
    session_factory: sessionmaker[Session],
) -> None:
    """一次性费用修正参与扣能后应扣减 remaining_uses 并失效。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                SkillDefinition(
                    skill_id="skill_once_cost",
                    skill_name="once cost skill",
                    element_type="normal",
                    skill_category="physical",
                    base_power=50,
                    base_energy_cost=3,
                    priority_modifier=0,
                ),
                EffectDefinition(
                    effect_id="effect_team_energy_cost_down_layered",
                    effect_name="team cost down",
                    category="skill_modifier",
                    polarity="positive",
                    display_group="skill_modifier",
                    display_priority=1,
                    owner_scope="side",
                    target_scope="side",
                    attach_target_type="side",
                    skill_modifier_json=dumps_json(
                        {
                            "modifier_type": "energy_cost_delta",
                            "energy_cost_delta_per_layer": -1,
                        }
                    ),
                ),
                Battle(
                    battle_id="battle_once_cost",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=1,
                    self_active_elf_id="elf_self",
                    enemy_active_elf_id="elf_enemy",
                ),
            ]
        )
        session.flush()
        session.add(_elf_state("battle_once_cost", "self", "elf_self", energy=10))
        session.add(_elf_state("battle_once_cost", "enemy", "elf_enemy", energy=10))
        session.add(
            BattleEffectInstance(
                instance_id="effect_once_cost",
                battle_id="battle_once_cost",
                effect_id="effect_team_energy_cost_down_layered",
                category="skill_modifier",
                owner_scope="side",
                owner_side="self",
                layers=2,
                remaining_uses=1,
                is_active=True,
                applied_turn=1,
            )
        )
        session.commit()

        event = BattleService(session).create_event(
            "battle_once_cost",
            BattleEventCreate(
                turn_number=1,
                event_type=BattleEventType.SKILL_USE.value,
                actor_side="self",
                actor_elf_id="elf_self",
                target_side="enemy",
                target_elf_id="elf_enemy",
                skill_id="skill_once_cost",
                skill_confirmed=True,
                manual_override=True,
            ),
        )

        state = session.scalar(
            select(BattleElfState).where(
                BattleElfState.battle_id == "battle_once_cost",
                BattleElfState.side == "self",
                BattleElfState.elf_id == "elf_self",
            )
        )
        assert state is not None
        assert state.energy == 9
        instance = session.get(BattleEffectInstance, "effect_once_cost")
        assert instance is not None
        assert instance.is_active is False
        assert instance.remaining_uses == 0
        payload = loads_json(event.payload_json, {})
        assert payload["skill_runtime"]["effective_energy_cost"] == 1
        assert payload["skill_runtime"]["consumed_skill_modifier_effects"][0]["status"] == (
            "consumed"
        )


def test_damage_event_applies_and_consumes_one_use_power_modifier(
    session_factory: sessionmaker[Session],
) -> None:
    """下一次攻击威力修正应进入伤害上下文，并在伤害事件后消耗。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                SkillDefinition(
                    skill_id="skill_power_once",
                    skill_name="once power skill",
                    element_type="普通",
                    skill_category="physical",
                    base_power=50,
                    base_energy_cost=0,
                    priority_modifier=0,
                ),
                EffectDefinition(
                    effect_id="effect_skill_power_up_layered",
                    effect_name="skill power up",
                    category="skill_modifier",
                    polarity="positive",
                    display_group="skill_modifier",
                    display_priority=1,
                    owner_scope="elf",
                    target_scope="single_elf",
                    attach_target_type="elf",
                    skill_modifier_json=dumps_json(
                        {
                            "modifier_type": "skill_power_add",
                            "power_add_per_layer": 10,
                        }
                    ),
                ),
                Battle(
                    battle_id="battle_once_power",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=1,
                    self_active_elf_id="elf_self",
                    enemy_active_elf_id="elf_enemy",
                ),
            ]
        )
        session.flush()
        session.add(_elf_state("battle_once_power", "self", "elf_self", energy=10))
        session.add(_elf_state("battle_once_power", "enemy", "elf_enemy", energy=10))
        session.add(
            BattleEffectInstance(
                instance_id="effect_once_power",
                battle_id="battle_once_power",
                effect_id="effect_skill_power_up_layered",
                category="skill_modifier",
                owner_scope="elf",
                owner_side="self",
                owner_elf_id="elf_self",
                layers=7,
                remaining_uses=1,
                is_active=True,
                applied_turn=1,
            )
        )
        session.commit()

        result = DamageEventService(session).create_damage_event(
            "battle_once_power",
            DamageEventCreate(
                turn_number=1,
                attacker_side="self",
                attacker_elf_id="elf_self",
                defender_side="enemy",
                defender_elf_id="elf_enemy",
                skill_id="skill_power_once",
                skill_confirmed=True,
                damage_display_type=DamageDisplayType.SINGLE_DAMAGE,
                damage_value=100,
                sync_observation=False,
            ),
        )

        context = loads_json(result.damage_event.formula_context_json, {})
        skill_modifier = context["rule_resolution_details"]["skill_modifier"][0]
        assert skill_modifier["effect_instance_id"] == "effect_once_power"
        assert skill_modifier["power_add"] == "70"
        assert str(context["flat_power_bonus"]) == "70"
        instance = session.get(BattleEffectInstance, "effect_once_power")
        assert instance is not None
        assert instance.is_active is False
        assert instance.remaining_uses == 0
        event_payload = loads_json(result.battle_event.payload_json, {})
        assert event_payload["consumed_skill_modifier_effects"][0]["effect_instance_id"] == (
            "effect_once_power"
        )


def test_combo_damage_event_uses_manual_hit_count_for_total_and_context(
    session_factory: sessionmaker[Session],
) -> None:
    """连击伤害事件应以手动连击数为准，并用单段×次数更新总伤害。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.flush()
        skill = session.get(SkillDefinition, "skill_attack")
        assert skill is not None
        skill.hit_rule_json = dumps_json(
            {
                "damage_display_type": "combo_repeated_damage",
                "runtime_record_strategy": "per_hit_damage",
                "hit_count": 3,
            }
        )
        session.add(
            Battle(
                battle_id="battle_combo_damage",
                phase=BattlePhase.BATTLE.value,
                turn_number=1,
                self_active_elf_id="elf_self",
                enemy_active_elf_id="elf_enemy",
            )
        )
        session.flush()
        session.add(_elf_state("battle_combo_damage", "self", "elf_self", energy=10))
        session.add(_elf_state("battle_combo_damage", "enemy", "elf_enemy", energy=10))
        session.commit()

        result = DamageEventService(session).create_damage_event(
            "battle_combo_damage",
            DamageEventCreate(
                turn_number=1,
                attacker_side="self",
                attacker_elf_id="elf_self",
                defender_side="enemy",
                defender_elf_id="elf_enemy",
                skill_id="skill_attack",
                skill_confirmed=True,
                damage_display_type=DamageDisplayType.COMBO_REPEATED_DAMAGE,
                per_hit_damage_value=45,
                hit_count=2,
                sync_observation=False,
            ),
        )

        assert result.damage_event.damage_value == 90
        assert result.damage_event.computed_total_damage_value == 90
        context = loads_json(result.damage_event.formula_context_json, {})
        assert context["hit_count"] == 2
        assert context["rule_resolution_details"]["hit_rule"]["source"] == "manual_payload"
        assert context["rule_resolution_details"]["hit_rule"]["skill_hit_count"] == 3
        enemy_state = session.scalar(
            select(BattleElfState).where(
                BattleElfState.battle_id == "battle_combo_damage",
                BattleElfState.side == "enemy",
                BattleElfState.elf_id == "elf_enemy",
            )
        )
        assert enemy_state is not None
        assert enemy_state.current_hp_value == 410
        resource_event = session.scalar(
            select(ResourceChangeEvent).where(
                ResourceChangeEvent.battle_id == "battle_combo_damage",
                ResourceChangeEvent.resource_type == "hp",
            )
        )
        assert resource_event is not None
        assert resource_event.value == 90


def test_conditional_mark_skill_modifiers_require_matching_flags(
    session_factory: sessionmaker[Session],
) -> None:
    """条件类印记必须等玩家/事件明确标记后才进入威力公式。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                EffectDefinition(
                    effect_id="effect_windrise_mark",
                    effect_name="windrise mark",
                    category="mark",
                    polarity="positive",
                    display_group="mark",
                    display_priority=1,
                    owner_scope="side",
                    target_scope="side",
                    attach_target_type="side",
                    skill_modifier_json=dumps_json(
                        {
                            "modifier_type": "skill_power_multiplier",
                            "power_multiplier_add_per_layer": 0.2,
                            "required_condition_flag": "actor_moves_before_target",
                            "skill_category": "physical_or_magic",
                        }
                    ),
                ),
                EffectDefinition(
                    effect_id="effect_electric_charge_mark",
                    effect_name="electric charge mark",
                    category="mark",
                    polarity="positive",
                    display_group="mark",
                    display_priority=2,
                    owner_scope="side",
                    target_scope="side",
                    attach_target_type="side",
                    skill_modifier_json=dumps_json(
                        {
                            "modifier_type": "burst_power_add",
                            "skill_category": "physical_or_magic",
                            "power_add_per_layer": 10,
                            "requires_burst": True,
                        }
                    ),
                ),
            ]
        )
        session.commit()

        snapshot_payload = [
            {
                "effect_id": "effect_windrise_mark",
                "owner_scope": "side",
                "owner_side": "self",
                "layers": 2,
            },
            {
                "effect_id": "effect_electric_charge_mark",
                "owner_scope": "side",
                "owner_side": "self",
                "layers": 2,
            },
        ]
        context = DamageFormulaContext(
            battle_id="battle_modifier_flags",
            attacker_side="self",
            defender_side="enemy",
            skill_category="magic",
            base_power=50,
            snapshot_payload=snapshot_payload,
        )

        service = BattleService(session)
        no_flags = service._skill_power_modifier_from_effects(context, snapshot_payload, "")
        assert no_flags["items"] == []
        assert no_flags["flat_power_bonus"] == 0

        context.rule_resolution_details["condition_flags"] = {
            "actor_moves_before_target": True,
            "burst_triggered": True,
        }
        with_flags = service._skill_power_modifier_from_effects(context, snapshot_payload, "")
        assert str(with_flags["multiplier"]) == "1.4"
        assert with_flags["flat_power_bonus"] == 20


def test_cute_mark_adds_one_layer_to_new_positive_stat_buff(
    session_factory: sessionmaker[Session],
) -> None:
    """萌化印记只给新获得的属性类增益额外 +1 层。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                SkillDefinition(
                    skill_id="skill_gain_attack",
                    skill_name="gain attack",
                    element_type="normal",
                    skill_category="status",
                    base_power=None,
                    base_energy_cost=0,
                    priority_modifier=0,
                    effect_operations_json=dumps_json(
                        [
                            {
                                "op_type": "apply_effect",
                                "effect_id": "effect_attack_up_layered",
                                "target": "actor_side",
                                "layers": 1,
                                "condition": "always",
                            }
                        ]
                    ),
                ),
                EffectDefinition(
                    effect_id="effect_cute_mark",
                    effect_name="cute mark",
                    category="mark",
                    polarity="positive",
                    display_group="mark",
                    display_priority=1,
                    owner_scope="side",
                    target_scope="side",
                    attach_target_type="side",
                ),
                EffectDefinition(
                    effect_id="effect_attack_up_layered",
                    effect_name="attack up",
                    category="stat_modifier",
                    polarity="positive",
                    display_group="stat_modifier",
                    display_priority=2,
                    owner_scope="side",
                    target_scope="side",
                    attach_target_type="side",
                    stack_rule="add_layers",
                    stat_modifier_json=dumps_json(
                        {
                            "modifier_type": "stat_stage",
                            "stat": "physical_attack",
                            "value_per_layer": 0.1,
                        }
                    ),
                ),
                Battle(
                    battle_id="battle_cute_mark_bonus",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=1,
                    self_active_elf_id="elf_self",
                    enemy_active_elf_id="elf_enemy",
                ),
            ]
        )
        session.flush()
        session.add(_elf_state("battle_cute_mark_bonus", "self", "elf_self", energy=10))
        session.add(_elf_state("battle_cute_mark_bonus", "enemy", "elf_enemy", energy=10))
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_cute",
                battle_id="battle_cute_mark_bonus",
                effect_id="effect_cute_mark",
                category="mark",
                owner_scope="side",
                owner_side="self",
                layers=3,
                is_active=True,
                applied_turn=1,
            )
        )
        session.commit()

        event = BattleService(session).create_event(
            "battle_cute_mark_bonus",
            BattleEventCreate(
                turn_number=1,
                event_type=BattleEventType.SKILL_USE.value,
                actor_side="self",
                actor_elf_id="elf_self",
                target_side="enemy",
                target_elf_id="elf_enemy",
                skill_id="skill_gain_attack",
                skill_confirmed=True,
                manual_override=True,
            ),
        )

        applied = session.scalar(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == "battle_cute_mark_bonus",
                BattleEffectInstance.effect_id == "effect_attack_up_layered",
                BattleEffectInstance.owner_side == "self",
                BattleEffectInstance.is_active.is_(True),
            )
        )
        assert applied is not None
        assert applied.layers == 2
        payload = loads_json(event.payload_json, {})
        result = payload["effect_operation_results"][0]
        assert result["layer_bonus_sources"][0]["reason"] == "cute_mark_positive_stat_bonus"


def test_burst_is_auto_eligible_on_initial_first_turn_and_records_effect(
    session_factory: sessionmaker[Session],
) -> None:
    """初始首发首回合可触发迸发，并记录具体附加效果。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                SkillDefinition(
                    skill_id="skill_burst_attack",
                    skill_name="burst attack",
                    element_type="normal",
                    skill_category="physical",
                    base_power=50,
                    base_energy_cost=1,
                    priority_modifier=0,
                ),
                EffectDefinition(
                    effect_id="effect_electric_charge_mark",
                    effect_name="electric charge mark",
                    category="mark",
                    polarity="positive",
                    display_group="mark",
                    display_priority=1,
                    owner_scope="side",
                    target_scope="side",
                    attach_target_type="side",
                    skill_modifier_json=dumps_json(
                        {
                            "modifier_type": "burst_power_add",
                            "skill_category": "physical_or_magic",
                            "power_add_per_layer": 10,
                            "requires_burst": True,
                        }
                    ),
                ),
                Battle(
                    battle_id="battle_burst_record",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=1,
                    self_active_elf_id="elf_self",
                    enemy_active_elf_id="elf_enemy",
                ),
            ]
        )
        session.flush()
        self_state = _elf_state("battle_burst_record", "self", "elf_self", energy=10)
        self_state.last_switch_turn = 0
        enemy_state = _elf_state("battle_burst_record", "enemy", "elf_enemy", energy=10)
        session.add_all([self_state, enemy_state])
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_burst",
                battle_id="battle_burst_record",
                effect_id="effect_electric_charge_mark",
                category="mark",
                owner_scope="side",
                owner_side="self",
                layers=2,
                is_active=True,
                applied_turn=1,
            )
        )
        session.commit()

        event = BattleService(session).create_event(
            "battle_burst_record",
            BattleEventCreate(
                turn_number=1,
                event_type=BattleEventType.SKILL_USE.value,
                actor_side="self",
                actor_elf_id="elf_self",
                target_side="enemy",
                target_elf_id="elf_enemy",
                skill_id="skill_burst_attack",
                skill_confirmed=True,
                manual_override=True,
            ),
        )

        payload = loads_json(event.payload_json, {})
        assert payload["condition_flags"]["burst_active"] is True
        assert payload["burst_effects"][0]["effect_id"] == "effect_electric_charge_mark"
        assert payload["burst_effects"][0]["power_add"] == "20"
        burst_event = session.get(BattleEvent, payload["burst_trigger_event_id"])
        assert burst_event is not None
        burst_payload = loads_json(burst_event.payload_json, {})
        assert burst_payload["trigger_type"] == "burst"
        assert burst_payload["burst_effects"][0]["power_add"] == "20"


def test_charge_skill_consumes_on_first_turn_and_releases_same_skill_next_turn(
    session_factory: sessionmaker[Session],
) -> None:
    """蓄力技能第一次选择扣能进入蓄力；再次选择同技能释放并清除蓄力。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                SkillDefinition(
                    skill_id="skill_charge_attack",
                    skill_name="charge attack",
                    element_type="normal",
                    skill_category="physical",
                    base_power=60,
                    base_energy_cost=3,
                    priority_modifier=0,
                    damage_rule_json=dumps_json(
                        {
                            "manual_review": {
                                "future_hooks": [
                                    {
                                        "hook_type": "charge_turn_mechanic",
                                        "status": "reserved",
                                    }
                                ]
                            }
                        }
                    ),
                ),
                EffectDefinition(
                    effect_id="effect_charge_ready",
                    effect_name="charge ready",
                    category="action_modifier",
                    polarity="positive",
                    display_group="action_modifier",
                    display_priority=1,
                    owner_scope="elf",
                    target_scope="single_elf",
                    attach_target_type="elf",
                    stack_rule="refresh",
                    clear_on_switch=True,
                ),
                Battle(
                    battle_id="battle_charge_skill",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=1,
                    self_active_elf_id="elf_self",
                    enemy_active_elf_id="elf_enemy",
                ),
            ]
        )
        session.flush()
        session.add(_elf_state("battle_charge_skill", "self", "elf_self", energy=10))
        session.add(_elf_state("battle_charge_skill", "enemy", "elf_enemy", energy=10))
        session.commit()

        first = BattleService(session).create_event(
            "battle_charge_skill",
            BattleEventCreate(
                turn_number=1,
                event_type=BattleEventType.SKILL_USE.value,
                actor_side="self",
                actor_elf_id="elf_self",
                target_side="enemy",
                target_elf_id="elf_enemy",
                skill_id="skill_charge_attack",
                skill_confirmed=True,
                manual_override=True,
            ),
        )

        state = session.scalar(
            select(BattleElfState).where(
                BattleElfState.battle_id == "battle_charge_skill",
                BattleElfState.side == "self",
                BattleElfState.elf_id == "elf_self",
            )
        )
        assert state is not None
        assert state.energy == 7
        first_payload = loads_json(first.payload_json, {})
        assert first_payload["skill_runtime"]["charge"]["phase"] == "charge_started"
        ready = session.scalar(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == "battle_charge_skill",
                BattleEffectInstance.effect_id == "effect_charge_ready",
                BattleEffectInstance.owner_elf_id == "elf_self",
                BattleEffectInstance.is_active.is_(True),
            )
        )
        assert ready is not None
        assert ready.source_skill_id == "skill_charge_attack"

        second = BattleService(session).create_event(
            "battle_charge_skill",
            BattleEventCreate(
                turn_number=2,
                event_type=BattleEventType.SKILL_USE.value,
                actor_side="self",
                actor_elf_id="elf_self",
                target_side="enemy",
                target_elf_id="elf_enemy",
                skill_id="skill_charge_attack",
                skill_confirmed=True,
                manual_override=True,
            ),
        )

        session.refresh(state)
        assert state.energy == 7
        second_payload = loads_json(second.payload_json, {})
        assert second_payload["skill_runtime"]["charge"]["phase"] == "charge_released"
        session.refresh(ready)
        assert ready.is_active is False


def test_dragon_bite_mark_triggers_dual_attack_buff_on_three_cost_skill(
    session_factory: sessionmaker[Session],
) -> None:
    """Dragon bite mark should grant dual attack layers when a 3-cost skill is used."""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                SkillDefinition(
                    skill_id="skill_cost_3_dragon",
                    skill_name="dragon trigger skill",
                    element_type="dragon",
                    skill_category="physical",
                    base_power=50,
                    base_energy_cost=3,
                    priority_modifier=0,
                ),
                EffectDefinition(
                    effect_id="effect_dragon_bite_mark",
                    effect_name="dragon bite mark",
                    category="mark",
                    polarity="positive",
                    display_group="mark",
                    display_priority=1,
                    owner_scope="side",
                    target_scope="side",
                    attach_target_type="side",
                    special_rule_id="dragon_bite_mark",
                ),
                EffectDefinition(
                    effect_id="effect_dual_attack_up_layered",
                    effect_name="dual attack up",
                    category="stat_modifier",
                    polarity="positive",
                    display_group="stat_modifier",
                    display_priority=2,
                    owner_scope="elf",
                    target_scope="single_elf",
                    attach_target_type="elf",
                    stack_rule="add_layers",
                    stat_modifier_json=dumps_json(
                        {
                            "modifier_type": "stat_stage",
                            "modifiers": [
                                {
                                    "modifier_type": "stat_stage",
                                    "stat": "physical_attack",
                                    "value_type": "percent_add",
                                    "value_per_layer": 0.1,
                                },
                                {
                                    "modifier_type": "stat_stage",
                                    "stat": "magic_attack",
                                    "value_type": "percent_add",
                                    "value_per_layer": 0.1,
                                },
                            ],
                        }
                    ),
                ),
                Battle(
                    battle_id="battle_dragon_mark",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=1,
                    self_active_elf_id="elf_self",
                    enemy_active_elf_id="elf_enemy",
                ),
            ]
        )
        session.flush()
        session.add(_elf_state("battle_dragon_mark", "self", "elf_self", energy=10))
        session.add(_elf_state("battle_dragon_mark", "enemy", "elf_enemy", energy=10))
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_dragon",
                battle_id="battle_dragon_mark",
                effect_id="effect_dragon_bite_mark",
                category="mark",
                owner_scope="side",
                owner_side="self",
                layers=1,
                is_active=True,
                applied_turn=1,
            )
        )
        session.commit()

        event = BattleService(session).create_event(
            "battle_dragon_mark",
            BattleEventCreate(
                turn_number=1,
                event_type=BattleEventType.SKILL_USE.value,
                actor_side="self",
                actor_elf_id="elf_self",
                target_side="enemy",
                target_elf_id="elf_enemy",
                skill_id="skill_cost_3_dragon",
                skill_confirmed=True,
                manual_override=True,
            ),
        )

        applied = session.scalar(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == "battle_dragon_mark",
                BattleEffectInstance.effect_id == "effect_dual_attack_up_layered",
                BattleEffectInstance.owner_side == "self",
                BattleEffectInstance.owner_elf_id == "elf_self",
                BattleEffectInstance.is_active.is_(True),
            )
        )
        assert applied is not None
        assert applied.layers == 3
        payload = loads_json(event.payload_json, {})
        assert any(
            item.get("effect_id") == "effect_dual_attack_up_layered"
            for item in payload["effect_operation_results"]
        )


def test_end_turn_resource_mark_gains_energy(
    session_factory: sessionmaker[Session],
) -> None:
    """End-turn resource marks should create energy gain events."""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                EffectDefinition(
                    effect_id="effect_photosynthesis_mark",
                    effect_name="photosynthesis mark",
                    category="mark",
                    polarity="positive",
                    display_group="mark",
                    display_priority=1,
                    owner_scope="side",
                    target_scope="side",
                    attach_target_type="side",
                    formula_hooks_json=dumps_json(["end_turn_resource_change"]),
                    resource_modifier_json=dumps_json(
                        {
                            "settlement_type": "end_turn",
                            "operation": "resource_change",
                            "resource_type": "energy",
                            "change_type": "gain",
                            "value_per_layer": 1,
                        }
                    ),
                ),
                Battle(
                    battle_id="battle_resource_mark",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=1,
                    self_active_elf_id="elf_self",
                    enemy_active_elf_id="elf_enemy",
                ),
            ]
        )
        session.flush()
        session.add(_elf_state("battle_resource_mark", "self", "elf_self", energy=5))
        session.add(_elf_state("battle_resource_mark", "enemy", "elf_enemy", energy=10))
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_photo",
                battle_id="battle_resource_mark",
                effect_id="effect_photosynthesis_mark",
                category="mark",
                owner_scope="side",
                owner_side="self",
                layers=2,
                is_active=True,
                applied_turn=1,
            )
        )
        session.commit()

        battle = session.get(Battle, "battle_resource_mark")
        assert battle is not None
        summaries = TurnSettlementService(session).settle_end_turn(battle, 1)

        state = session.scalar(
            select(BattleElfState).where(
                BattleElfState.battle_id == "battle_resource_mark",
                BattleElfState.side == "self",
                BattleElfState.elf_id == "elf_self",
            )
        )
        assert state is not None
        assert state.energy == 7
        assert summaries[0]["resource_type"] == "energy"
        resource_event = session.scalar(
            select(ResourceChangeEvent).where(
                ResourceChangeEvent.battle_id == "battle_resource_mark"
            )
        )
        assert resource_event is not None
        assert resource_event.change_type == "gain"


def test_switch_in_resource_mark_loses_energy(
    session_factory: sessionmaker[Session],
) -> None:
    """入场资源印记应在切换上场时结算扣能。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                ElfDefinition(
                    elf_id="elf_bench",
                    elf_name="己方替补测试精灵",
                    avatar="",
                    element_types_json=dumps_json(["普通"]),
                    base_hp_talent=100,
                    base_physical_attack_talent=100,
                    base_physical_defense_talent=100,
                    base_magic_attack_talent=100,
                    base_magic_defense_talent=100,
                    base_speed_talent=100,
                ),
                EffectDefinition(
                    effect_id="effect_spiritfall_mark",
                    effect_name="spiritfall mark",
                    category="mark",
                    polarity="negative",
                    display_group="mark",
                    display_priority=1,
                    owner_scope="side",
                    target_scope="side",
                    attach_target_type="side",
                    formula_hooks_json=dumps_json(["switch_in_resource_change"]),
                    resource_modifier_json=dumps_json(
                        {
                            "settlement_type": "switch_in",
                            "operation": "resource_change",
                            "resource_type": "energy",
                            "change_type": "lose",
                            "value_per_layer": 1,
                        }
                    ),
                ),
                Battle(
                    battle_id="battle_spiritfall_mark",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=2,
                    self_active_elf_id="elf_self",
                    enemy_active_elf_id="elf_enemy",
                ),
            ]
        )
        session.flush()
        active = _elf_state("battle_spiritfall_mark", "self", "elf_self", energy=10)
        bench = _elf_state("battle_spiritfall_mark", "self", "elf_bench", energy=6)
        bench.is_active_elf = False
        enemy = _elf_state("battle_spiritfall_mark", "enemy", "elf_enemy", energy=10)
        session.add_all([active, bench, enemy])
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_spiritfall",
                battle_id="battle_spiritfall_mark",
                effect_id="effect_spiritfall_mark",
                category="mark",
                owner_scope="side",
                owner_side="self",
                layers=2,
                is_active=True,
                applied_turn=1,
            )
        )
        session.commit()

        BattleService(session).switch_elf(
            "battle_spiritfall_mark",
            SwitchElfInput(side="self", elf_id="elf_bench", turn_number=2),
        )

        switched_in = session.scalar(
            select(BattleElfState).where(
                BattleElfState.battle_id == "battle_spiritfall_mark",
                BattleElfState.side == "self",
                BattleElfState.elf_id == "elf_bench",
            )
        )
        assert switched_in is not None
        assert switched_in.energy == 4
        resource_event = session.scalar(
            select(ResourceChangeEvent).where(
                ResourceChangeEvent.battle_id == "battle_spiritfall_mark",
                ResourceChangeEvent.target_elf_id == "elf_bench",
            )
        )
        assert resource_event is not None
        assert resource_event.change_type == "lose"
        assert resource_event.value == 2


def test_return_to_field_switch_clears_switch_clear_effects(
    session_factory: sessionmaker[Session],
) -> None:
    """返场应按 from=to 的切换事件执行切换清除。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                EffectDefinition(
                    effect_id="effect_charge_ready",
                    effect_name="charge ready",
                    category="action_modifier",
                    polarity="positive",
                    display_group="action_modifier",
                    display_priority=1,
                    owner_scope="elf",
                    target_scope="single_elf",
                    attach_target_type="elf",
                    stack_rule="refresh",
                    clear_on_switch=True,
                ),
                Battle(
                    battle_id="battle_return_to_field",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=3,
                    self_active_elf_id="elf_self",
                    enemy_active_elf_id="elf_enemy",
                ),
            ]
        )
        session.flush()
        session.add(_elf_state("battle_return_to_field", "self", "elf_self", energy=10))
        session.add(_elf_state("battle_return_to_field", "enemy", "elf_enemy", energy=10))
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_charge_ready_return",
                battle_id="battle_return_to_field",
                effect_id="effect_charge_ready",
                category="action_modifier",
                owner_scope="elf",
                owner_side="self",
                owner_elf_id="elf_self",
                layers=1,
                is_active=True,
                applied_turn=2,
            )
        )
        session.commit()

        BattleService(session).switch_elf(
            "battle_return_to_field",
            SwitchElfInput(side="self", elf_id="elf_self", turn_number=3),
        )

        event = session.scalar(
            select(BattleEvent).where(
                BattleEvent.battle_id == "battle_return_to_field",
                BattleEvent.event_type == BattleEventType.SWITCH_ELF.value,
            )
        )
        assert event is not None
        payload = loads_json(event.payload_json, {})
        assert payload["from_elf_id"] == "elf_self"
        assert payload["to_elf_id"] == "elf_self"
        assert payload["switch_mode"] == "return_to_field"

        instance = session.get(BattleEffectInstance, "effect_instance_charge_ready_return")
        assert instance is not None
        assert instance.is_active is False


def test_runtime_form_change_preserves_build_and_updates_effective_damage_preview(
    session_factory: sessionmaker[Session],
) -> None:
    """退化/形态回退应保留原精灵身份和培养，只替换有效形态参与面板与本系计算。"""
    with session_factory() as session:
        _seed_static_rules(session)
        session.add_all(
            [
                ElfDefinition(
                    elf_id="elf_degenerated",
                    elf_name="退化形态",
                    avatar="",
                    element_types_json=dumps_json(["火"]),
                    base_hp_talent=50,
                    base_physical_attack_talent=80,
                    base_physical_defense_talent=60,
                    base_magic_attack_talent=70,
                    base_magic_defense_talent=65,
                    base_speed_talent=90,
                ),
                SkillDefinition(
                    skill_id="skill_fire",
                    skill_name="火系攻击",
                    element_type="火",
                    skill_category="physical",
                    base_power=40,
                    base_energy_cost=0,
                    priority_modifier=0,
                ),
                Battle(
                    battle_id="battle_runtime_form",
                    phase=BattlePhase.PREPARATION.value,
                ),
            ]
        )
        individual = {
            "hp": 10,
            "physical_attack": 7,
            "physical_defense": 0,
            "magic_attack": 0,
            "magic_defense": 0,
            "speed": 10,
        }
        session.add(
            PlayerElfBuild(
                build_id="build_runtime_form",
                elf_id="elf_self",
                nature_id="nature_test",
                individual_talent_distribution_json=dumps_json(individual),
                final_stats_json=dumps_json(
                    {
                        "hp": 400,
                        "physical_attack": 160,
                        "physical_defense": 120,
                        "magic_attack": 120,
                        "magic_defense": 120,
                        "speed": 150,
                    }
                ),
            )
        )
        session.flush()
        session.add(
            PlayerElfBuildSkill(
                build_id="build_runtime_form",
                slot_index=0,
                skill_id="skill_fire",
            )
        )
        session.commit()

        service = BattleService(session)
        service.setup_lineup(
            "battle_runtime_form",
            LineupInput(
                elves=[
                    {
                        "side": "self",
                        "elf_id": "elf_self",
                        "build_id": "build_runtime_form",
                        "is_active_elf": True,
                    },
                    {"side": "enemy", "elf_id": "elf_enemy", "is_active_elf": True},
                ]
            ),
        )
        battle = session.get(Battle, "battle_runtime_form")
        assert battle is not None
        battle.phase = BattlePhase.BATTLE.value
        battle.self_active_elf_id = "elf_self"
        battle.enemy_active_elf_id = "elf_enemy"
        self_state = session.scalar(
            select(BattleElfState).where(
                BattleElfState.battle_id == "battle_runtime_form",
                BattleElfState.side == "self",
            )
        )
        enemy_state = session.scalar(
            select(BattleElfState).where(
                BattleElfState.battle_id == "battle_runtime_form",
                BattleElfState.side == "enemy",
            )
        )
        assert self_state is not None
        assert enemy_state is not None
        self_state.current_hp_percent = 50.0
        enemy_state.panel_stats_json = dumps_json(
            {
                "hp": 300,
                "physical_attack": 100,
                "physical_defense": 100,
                "magic_attack": 100,
                "magic_defense": 100,
                "speed": 100,
            }
        )
        enemy_state.current_hp_value = 300
        session.commit()

        state_out = service.change_runtime_form(
            "battle_runtime_form",
            self_state.state_id,
            RuntimeFormChangeInput(
                effective_elf_id="elf_degenerated",
                reason="test_degenerate",
            ),
        )

        session.refresh(self_state)
        panel = loads_json(self_state.panel_stats_json, {})
        assert self_state.elf_id == "elf_self"
        assert self_state.runtime_form_elf_id == "elf_degenerated"
        assert self_state.nature_id == "nature_test"
        assert loads_json(self_state.individual_talent_distribution_json, {}) == individual
        assert panel["hp"] == 306
        assert panel["physical_attack"] == 195
        assert self_state.current_hp_value == 153

        events = list(
            session.scalars(
                select(BattleEvent).where(BattleEvent.battle_id == "battle_runtime_form")
            ).all()
        )
        assert [event.event_type for event in events] == [
            BattleEventType.RUNTIME_FORM_CHANGE.value
        ]
        payload = loads_json(events[0].payload_json, {})
        assert payload["previous_effective_elf_id"] == "elf_self"
        assert payload["effective_elf_id"] == "elf_degenerated"

        self_out = next(item for item in state_out.elves if item["side"] == "self")
        assert self_out["effective_elf_id"] == "elf_degenerated"
        assert self_out["effective_form_source"] == "runtime_form"
        slot = next(item for item in state_out.skill_slots if item["skill_id"] == "skill_fire")
        assert slot["effective_elf_id"] == "elf_degenerated"
        assert slot["attacker_element_types"] == ["火"]
        assert slot["damage_preview"]["current_target"]["multipliers"]["stab"] == "1.25"

        replay = service.replay_from_event("battle_runtime_form", events[0].event_id)
        session.refresh(self_state)
        assert self_state.runtime_form_elf_id == "elf_degenerated"
        assert loads_json(self_state.panel_stats_json, {})["hp"] == 306
        assert "runtime_form_change" not in replay.runtime_unsupported_event_types


def _seed_static_rules(session: Session) -> None:
    session.add_all(
        [
            ElfDefinition(
                elf_id="elf_self",
                elf_name="己方测试精灵",
                avatar="",
                element_types_json=dumps_json(["普通"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
            ElfDefinition(
                elf_id="elf_enemy",
                elf_name="敌方测试精灵",
                avatar="",
                element_types_json=dumps_json(["普通"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
            NatureDefinition(
                nature_id="nature_test",
                nature_name="测试性格",
                positive_stat="physical_attack",
                positive_multiplier=1.0,
                negative_stat="physical_defense",
                negative_multiplier=1.0,
                neutral_multiplier=1.0,
            ),
            SkillDefinition(
                skill_id="skill_attack",
                skill_name="测试攻击",
                element_type="普通",
                skill_category="physical",
                base_power=50,
                base_energy_cost=0,
                priority_modifier=0,
            ),
        ]
    )


def _elf_state(battle_id: str, side: str, elf_id: str, *, energy: int) -> BattleElfState:
    return BattleElfState(
        state_id=f"state_{battle_id}_{side}_{elf_id}",
        battle_id=battle_id,
        side=side,
        elf_id=elf_id,
        elf_name="测试精灵",
        avatar="",
        panel_stats_json=dumps_json(
            {
                "hp": 500,
                "physical_attack": 100,
                "physical_defense": 100,
                "magic_attack": 100,
                "magic_defense": 100,
                "speed": 100,
            }
        ),
        current_hp_value=500,
        current_hp_percent=100.0,
        energy=energy,
        skill_ids_json=dumps_json([DEFAULT_COMMON_SKILL_ID]),
        confirmed_skill_ids_json=dumps_json([]),
        active_effect_instance_ids_json=dumps_json([]),
        is_active_elf=True,
        is_defeated=False,
        manual_override=True,
    )
