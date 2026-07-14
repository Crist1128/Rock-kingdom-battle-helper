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
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState, BattleSkillSlot
from app.models.event import BattleEvent
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
            ElfDefinition(
                elf_id="grass_ice_elf",
                elf_name="双重克制测试精灵",
                avatar="",
                element_types_json=dumps_json(["grass", "ice"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
            ElfDefinition(
                elf_id="water_earth_elf",
                elf_name="双重抵抗测试精灵",
                avatar="",
                element_types_json=dumps_json(["water", "earth"]),
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
            SkillDefinition(
                skill_id="defense_skill",
                skill_name="防御测试技能",
                element_type="normal",
                skill_category="status",
                base_power=None,
                base_energy_cost=1,
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
            SkillDefinition(
                skill_id="attack_response_skill",
                skill_name="attack response test",
                element_type="fire",
                skill_category="physical",
                base_power=50,
                base_energy_cost=0,
                priority_modifier=0,
                damage_rule_json=dumps_json(
                    {
                        "damage_type": "normal_formula",
                        "response_rule": {
                            "target": "status",
                            "condition": "response_status_success",
                            "success_multiplier": 3,
                            "modifier": "power_multiplier",
                        },
                    }
                ),
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
            TypeEffectivenessRule(
                attack_element_type="fire",
                defense_element_type="ice",
                multiplier=2.0,
            ),
            TypeEffectivenessRule(
                attack_element_type="fire",
                defense_element_type="earth",
                multiplier=0.5,
            ),
            TypeEffectivenessRule(
                attack_element_type="幻",
                defense_element_type="grass",
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


def test_rule_resolver_matches_chinese_and_english_element_aliases(
    db_session: Session,
) -> None:
    """中文 seed/payload 与英文 rocom 静态数据混用时，本系和克制倍率仍应命中。"""
    context = _context("grass_elf")
    context.skill_id = None
    context.skill_element_type = "火"
    context.attacker_element_types = ["fire"]
    context.defender_element_types = ["草"]
    context.skill_category = "physical"
    context.base_power = 50

    resolved = RuleResolver(db_session).resolve_damage_context(
        context,
        {"resolve_rules": True},
    )

    assert resolved.stab_multiplier == Decimal("1.25")
    assert resolved.type_multiplier == Decimal("2.0")


def test_rule_resolver_uses_skill_fixed_hit_count(db_session: Session) -> None:
    """固定连击技能应从 hit_rule_json 自动带入连击数。"""
    skill = db_session.get(SkillDefinition, "fire_skill")
    assert skill is not None
    skill.hit_rule_json = dumps_json(
        {
            "damage_display_type": "combo_repeated_damage",
            "runtime_record_strategy": "per_hit_damage",
            "hit_count": 3,
        }
    )

    context = RuleResolver(db_session).resolve_damage_context(
        _context("grass_elf"),
        {"resolve_rules": True},
    )

    assert context.hit_count == 3
    assert context.damage_display_type == "combo_repeated_damage"
    assert context.rule_resolution_details["hit_rule"]["source"] == "skill_hit_rule"
    result = DamageCalculator().calculate(context)
    assert result.explanation["single_damage"] == 225
    assert result.explanation["hit_count"] == 3
    assert result.explanation["hit_count_source"] == "skill_hit_rule"
    assert result.damage_value == 675


def test_rule_resolver_manual_hit_count_overrides_skill_rule(db_session: Session) -> None:
    """用户手动观测到的连击数应优先于静态技能库。"""
    skill = db_session.get(SkillDefinition, "fire_skill")
    assert skill is not None
    skill.hit_rule_json = dumps_json(
        {
            "hit_count": 3,
            "conditional_hit_rule": {
                "condition": "actor_hp_percent_below_50",
                "hit_count_bonus": 2,
            },
        }
    )

    context = RuleResolver(db_session).resolve_damage_context(
        _context("grass_elf"),
        {"resolve_rules": True, "hit_count": 2, "actor_hp_percent": 49},
    )

    assert context.hit_count == 2
    assert context.rule_resolution_details["hit_rule"]["source"] == "manual_payload"
    assert context.rule_resolution_details["hit_rule"]["skill_hit_count"] == 3
    assert context.rule_resolution_details["hit_rule"]["conditional_hit_rule"] == {
        "status": "skipped",
        "reason": "manual_hit_count_override",
    }


def test_rule_resolver_combines_dual_type_by_project_rule(db_session: Session) -> None:
    """双属性一克制一抵抗时，项目规则要求合并为 1，而不是简单相乘。"""
    context = RuleResolver(db_session).resolve_damage_context(
        _context("grass_water_elf"),
        {"resolve_rules": True},
    )

    assert context.defender_element_types == ["grass", "water"]
    assert context.type_multiplier == Decimal("1")


def test_rule_resolver_combines_double_strong_as_triple_damage(db_session: Session) -> None:
    """双重克制仍按三倍伤害处理。"""
    context = RuleResolver(db_session).resolve_damage_context(
        _context("grass_ice_elf"),
        {"resolve_rules": True},
    )

    assert context.defender_element_types == ["grass", "ice"]
    assert context.rule_resolution_details["type_multiplier"]["single_multipliers"] == [
        "2.0",
        "2.0",
    ]
    assert context.type_multiplier == Decimal("3")


def test_rule_resolver_combines_double_resist_as_quarter_damage(db_session: Session) -> None:
    """双重抵抗应为四倍免伤，即只受到四分之一伤害。"""
    context = RuleResolver(db_session).resolve_damage_context(
        _context("water_earth_elf"),
        {"resolve_rules": True},
    )

    assert context.defender_element_types == ["water", "earth"]
    assert context.rule_resolution_details["type_multiplier"]["single_multipliers"] == [
        "0.5",
        "0.5",
    ]
    assert context.type_multiplier == Decimal("0.25")


def test_rule_resolver_marks_unknown_when_response_branch_is_unknown(
    db_session: Session,
) -> None:
    """存在应对倍率但成功与否未知时，不应计算单点伤害并误导实时估计。"""
    context = RuleResolver(db_session).resolve_damage_context(
        _context("grass_elf"),
        {"resolve_rules": True, "response_success_multiplier": 3},
    )

    assert "response_success_unknown" in context.unknown_factors
    assert context.response_multiplier == Decimal("1")


def test_rule_resolver_applies_defense_skill_reduction(db_session: Session) -> None:
    """传入防御技能时，减伤应进入 damage_reductions 并参与普通伤害计算。"""
    context = RuleResolver(db_session).resolve_damage_context(
        _context("grass_elf"),
        {
            "resolve_rules": True,
            "defense_skill_id": "defense_skill",
            "response_attack_success": True,
        },
    )

    assert context.damage_reductions == [Decimal("0.7")]

    result = DamageCalculator().calculate(context)
    assert result.status == "calculated"
    assert result.damage_value == 67
    assert result.explanation["damage_reductions"] == ["0.7"]


def test_rule_resolver_loads_attack_skill_response_rule_power_multiplier(
    db_session: Session,
) -> None:
    """Attack skill response_rule should auto-load and modify current power."""
    context = _context("grass_elf")
    context.skill_id = "attack_response_skill"

    resolved = RuleResolver(db_session).resolve_damage_context(
        context,
        {"resolve_rules": True, "response_status_success": True},
    )

    assert resolved.power_multiplier == Decimal("3")
    assert resolved.rule_resolution_details["attack_skill_response_rule"]["skill_id"] == (
        "attack_response_skill"
    )
    assert resolved.rule_resolution_details["power_multiplier"]["value"] == "3"


def test_rule_resolver_keeps_attack_response_rule_unknown_without_success_flag(
    db_session: Session,
) -> None:
    """Missing response success flag should not apply attack skill response branch."""
    context = _context("grass_elf")
    context.skill_id = "attack_response_skill"

    resolved = RuleResolver(db_session).resolve_damage_context(context, {"resolve_rules": True})

    assert resolved.power_multiplier == Decimal("1")
    assert "response_success_unknown" in resolved.unknown_factors
    assert resolved.rule_resolution_details["power_multiplier"]["source"] == "rule_branch_unknown"


def test_rule_resolver_uses_runtime_skill_slot_current_power(db_session: Session) -> None:
    """Runtime skill slot current_power should override static base power."""
    db_session.add_all(
        [
            Battle(battle_id="battle_1", phase="battle", turn_number=1),
            BattleSkillSlot(
                slot_id="slot_power_override",
                battle_id="battle_1",
                side="self",
                elf_id="fire_elf",
                slot_index=0,
                skill_id="fire_skill",
                current_power=80,
            ),
        ]
    )
    db_session.commit()
    context = _context("grass_elf")
    context.attacker_side = "self"

    resolved = RuleResolver(db_session).resolve_damage_context(context, {"resolve_rules": True})

    assert resolved.base_power == 80
    assert resolved.rule_resolution_details["skill_slot_runtime"]["base_power_overridden"] is True


def test_rule_resolver_applies_conditional_hit_count_and_dynamic_layers(
    db_session: Session,
) -> None:
    """Conditional hit rules should support HP flags and snapshot effect layers."""
    skill = db_session.get(SkillDefinition, "fire_skill")
    assert skill is not None
    skill.hit_rule_json = dumps_json(
        {
            "damage_display_type": "combo_repeated_damage",
            "runtime_record_strategy": "per_hit_damage",
            "hit_count": 3,
            "conditional_hit_rule": {
                "condition": "actor_hp_percent_below_50",
                "hit_count_bonus": 2,
            },
        }
    )
    resolved = RuleResolver(db_session).resolve_damage_context(
        _context("grass_elf"),
        {"resolve_rules": True, "actor_hp_percent": 49},
    )
    assert resolved.hit_count == 5
    assert resolved.rule_resolution_details["hit_rule"]["source"] == "conditional_hit_rule"

    skill.hit_rule_json = dumps_json(
        {
            "hit_count": 1,
            "conditional_hit_rule": {
                "source_effect_id": "effect_starfall_mark",
                "source_target": "enemy_side",
                "hit_count_bonus_per_layer": 1,
            },
        }
    )
    context = _context("grass_elf")
    context.attacker_side = "self"
    context.defender_side = "enemy"
    context.snapshot_payload = [
        {
            "effect_id": "effect_starfall_mark",
            "owner_scope": "side",
            "owner_side": "enemy",
            "layers": 2,
        }
    ]
    resolved = RuleResolver(db_session).resolve_damage_context(
        context,
        {"resolve_rules": True},
    )
    assert resolved.hit_count == 3


def test_rule_resolver_applies_dynamic_power_rules(db_session: Session) -> None:
    """Dynamic power rules should read condition flags, marks, resources and history."""
    skill = db_session.get(SkillDefinition, "fire_skill")
    assert skill is not None
    skill.damage_rule_json = dumps_json(
        {
            "dynamic_power_rules": [
                {"condition": "actor_moves_before_target", "power_multiplier": 1.5},
                {
                    "source_category": "mark",
                    "source_target": "enemy_side",
                    "power_add_per_layer": 20,
                },
            ]
        }
    )
    context = _context("grass_elf")
    context.attacker_side = "self"
    context.defender_side = "enemy"
    context.snapshot_payload = [
        {
            "effect_id": "effect_starfall_mark",
            "category": "mark",
            "owner_scope": "side",
            "owner_side": "enemy",
            "layers": 2,
        }
    ]

    resolved = RuleResolver(db_session).resolve_damage_context(
        context,
        {
            "resolve_rules": True,
            "condition_flags": {"actor_moves_before_target": True},
        },
    )

    assert resolved.power_multiplier == Decimal("1.5")
    assert resolved.flat_power_bonus == Decimal("40")
    assert resolved.rule_resolution_details["dynamic_power_rules"][0]["status"] == "resolved"


def test_rule_resolver_applies_resource_and_previous_turn_power_rules(
    db_session: Session,
) -> None:
    """Energy-based and previous-turn response rules should be executable."""
    db_session.add_all(
        [
            Battle(battle_id="battle_1", phase="battle", turn_number=2),
            BattleElfState(
                state_id="enemy_state_power",
                battle_id="battle_1",
                side="enemy",
                elf_id="grass_elf",
                elf_name="enemy",
                avatar="",
                panel_stats_json=dumps_json({}),
                current_hp_percent=100,
                energy=3,
                is_active_elf=True,
                is_defeated=False,
                manual_override=True,
            ),
            BattleEvent(
                event_id="prev_response",
                battle_id="battle_1",
                turn_number=1,
                event_type="skill_use",
                actor_side="self",
                actor_elf_id="fire_elf",
                payload_json=dumps_json({"response_status_success": True}),
                source="manual_input",
                manual_override=True,
            ),
        ]
    )
    skill = db_session.get(SkillDefinition, "fire_skill")
    assert skill is not None
    skill.damage_rule_json = dumps_json(
        {
            "dynamic_power_rules": [
                {
                    "source_resource": "energy",
                    "source_target": "enemy_side",
                    "power_multiplier_delta_per_point": -0.1,
                },
                {"condition": "previous_turn_response_success", "power_add": 180},
            ]
        }
    )
    db_session.commit()
    context = _context("grass_elf")
    context.attacker_side = "self"
    context.attacker_elf_id = "fire_elf"
    context.defender_side = "enemy"
    context.defender_elf_id = "grass_elf"

    resolved = RuleResolver(db_session).resolve_damage_context(
        context,
        {"resolve_rules": True, "turn_number": 2},
    )

    assert resolved.power_multiplier == Decimal("0.7")
    assert resolved.flat_power_bonus == Decimal("180")


def test_rule_resolver_uses_starfall_element_for_type_multiplier(db_session: Session) -> None:
    """星陨应按自身幻系结算克制，而不是按触发技能系别结算。"""
    context = _context("grass_elf")
    context.formula_type = "starfall"
    context.trigger_skill_element_type = "fire"
    context.trigger_skill_category = "physical"
    context.effect_id = "effect_starfall_mark"
    context.effect_layers = 1

    resolved = RuleResolver(db_session).resolve_damage_context(context, {"resolve_rules": True})

    assert resolved.skill_element_type == "fire"
    assert resolved.rule_resolution_details["type_multiplier"]["attack_element_type"] == "幻"
    assert resolved.type_multiplier == Decimal("0.5")
