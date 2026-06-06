"""伤害事件服务的真实样例回归测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState
from app.models.event import ResourceChangeEvent
from app.models.static import ElfDefinition, SkillDefinition
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
            hp_percent_before=100,
            hp_percent_after=83,
        ),
    )

    assert result.inference_result["status"] == "calculated"
    assert result.inference_result["confidence"] == 1.0
    assert result.damage_event.calculation_confidence == 1.0

    formula_context = loads_json(result.damage_event.formula_context_json, {})
    assert formula_context["skill_category"] == "physical"
    assert formula_context["base_power"] == 50
    assert formula_context["stab_multiplier"] == "1.25"
    assert formula_context["type_multiplier"] == "1"
    assert formula_context["attacker_panel_stats"]["physical_attack"] == 277
    assert formula_context["defender_panel_stats"]["physical_defense"] == 204


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
