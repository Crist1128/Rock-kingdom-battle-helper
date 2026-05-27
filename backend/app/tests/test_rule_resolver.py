"""RuleResolver 第四阶段雏形测试。

这些测试确认规则解析层可以把“技能/属性/应对/减伤”等业务输入，转换为
DamageCalculator 可直接消费的倍率字段。
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext, PanelStats
from app.calculation.rule_resolver import RuleResolver
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import ElfDefinition, SkillDefinition, TypeEffectivenessRule
from app.utils.json import dumps_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建规则解析测试用的独立内存数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    session = session_factory()
    session.add_all(
        [
            ElfDefinition(
                elf_id="fire_elf",
                elf_name="火系测试精灵",
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
                elf_id="grass_elf",
                elf_name="草系测试精灵",
                avatar="",
                element_types_json=dumps_json(["grass"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
            ElfDefinition(
                elf_id="grass_water_elf",
                elf_name="草水双系测试精灵",
                avatar="",
                element_types_json=dumps_json(["grass", "water"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
            SkillDefinition(
                skill_id="fire_skill",
                skill_name="火系测试技能",
                element_type="fire",
                skill_category="physical",
                base_power=50,
                base_energy_cost=0,
                priority_modifier=0,
            ),
            TypeEffectivenessRule(
                attack_element_type="fire",
                defense_element_type="grass",
                multiplier=2.0,
            ),
            TypeEffectivenessRule(
                attack_element_type="fire",
                defense_element_type="water",
                multiplier=0.5,
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


def _context(defender_elf_id: str) -> DamageFormulaContext:
    """构造最小伤害上下文，技能和系别由 RuleResolver 补齐。"""
    return DamageFormulaContext(
        battle_id="battle_1",
        damage_event_id="damage_rule_1",
        attacker_elf_id="fire_elf",
        defender_elf_id=defender_elf_id,
        skill_id="fire_skill",
        attacker_panel_stats=PanelStats(
            hp=300,
            physical_attack=200,
            physical_defense=100,
            magic_attack=100,
            magic_defense=100,
            speed=100,
        ),
        defender_panel_stats=PanelStats(
            hp=300,
            physical_attack=100,
            physical_defense=100,
            magic_attack=100,
            magic_defense=100,
            speed=100,
        ),
    )


def test_rule_resolver_fills_skill_stab_and_single_type_multiplier(db_session: Session) -> None:
    """单属性防御时，应从数据库补齐技能字段、本系加成和克制倍率。"""
    context = RuleResolver(db_session).resolve_damage_context(
        _context("grass_elf"),
        {"resolve_rules": True},
    )

    assert context.skill_category == "physical"
    assert context.base_power == 50
    assert context.skill_element_type == "fire"
    assert context.attacker_element_types == ["fire"]
    assert context.defender_element_types == ["grass"]
    assert context.stab_multiplier == Decimal("1.25")
    assert context.type_multiplier == Decimal("2.0")

    result = DamageCalculator().calculate(context)
    assert result.status == "calculated"
    assert result.damage_value == 225
    assert result.explanation["rule_resolution_enabled"] is True


def test_rule_resolver_combines_dual_type_by_project_rule(db_session: Session) -> None:
    """双属性一克制一抵抗时，项目规则要求合并为 1，而不是简单相乘。"""
    context = RuleResolver(db_session).resolve_damage_context(
        _context("grass_water_elf"),
        {"resolve_rules": True},
    )

    assert context.defender_element_types == ["grass", "water"]
    assert context.type_multiplier == Decimal("1")


def test_rule_resolver_marks_unknown_when_response_branch_is_unknown(
    db_session: Session,
) -> None:
    """存在应对倍率但成功与否未知时，不应计算单点伤害并误导候选扣分。"""
    context = RuleResolver(db_session).resolve_damage_context(
        _context("grass_elf"),
        {"resolve_rules": True, "response_success_multiplier": 3},
    )

    assert "response_success_unknown" in context.unknown_factors
    assert context.response_multiplier == Decimal("1")
