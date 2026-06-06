"""核心默认技能与战斗初始资源测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.default_skills import DEFAULT_COMMON_SKILL_ID, DEFAULT_INITIAL_ENERGY
from app.core.enums import BattleEventType, BattlePhase
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState
from app.models.event import ResourceChangeEvent
from app.models.static import (
    ElfDefinition,
    NatureDefinition,
    PlayerElfBuild,
    PlayerElfBuildSkill,
    SkillDefinition,
)
from app.schemas.battle import LineupInput
from app.schemas.event import BattleEventCreate
from app.seed.core_skills import ensure_core_skills
from app.services.battle_service import BattleService
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
