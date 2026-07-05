"""ModifierResolver 与 ResponseResolver 的 E 阶段聚焦测试。"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.calculation.formula_context import DamageFormulaContext
from app.calculation.modifier_resolver import ModifierResolver
from app.calculation.response_resolver import ResponseResolver
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState
from app.models.event import BattleEvent
from app.models.static import EffectDefinition, ElfDefinition, SkillDefinition
from app.services.battle_service import BattleService
from app.utils.json import dumps_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建解析器测试用的独立内存数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    session = session_factory()
    session.add_all(
        [
            SkillDefinition(
                skill_id="defense_skill",
                skill_name="防御测试",
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
            EffectDefinition(
                effect_id="effect_guard",
                effect_name="守护测试",
                category="mark",
                polarity="positive",
                display_group="mark",
                display_priority=100,
                owner_scope="elf",
                target_scope="single_elf",
                attach_target_type="elf",
                damage_modifier_json=dumps_json(
                    {
                        "damage_type": "defense_modifier",
                        "damage_reduction": 0.5,
                        "active": True,
                    }
                ),
            ),
            EffectDefinition(
                effect_id="weather_rain",
                effect_name="雨天",
                category="weather",
                polarity="neutral",
                display_group="weather",
                display_priority=300,
                owner_scope="field",
                target_scope="field",
                attach_target_type="field",
                skill_modifier_json=dumps_json(
                    {
                        "modifier_type": "damage_bonus",
                        "element_type": "水",
                        "value_type": "percent_add",
                        "value": 0.75,
                    }
                ),
            ),
            EffectDefinition(
                effect_id="weather_sandstorm",
                effect_name="沙暴",
                category="weather",
                polarity="neutral",
                display_group="weather",
                display_priority=310,
                owner_scope="field",
                target_scope="field",
                attach_target_type="field",
                skill_modifier_json=dumps_json(
                    {
                        "modifier_type": "damage_bonus",
                        "element_type": "地",
                        "value_type": "percent_add",
                        "value": 0.75,
                    }
                ),
            ),
            EffectDefinition(
                effect_id="weather_blizzard",
                effect_name="暴风雪",
                category="weather",
                polarity="neutral",
                display_group="weather",
                display_priority=320,
                owner_scope="field",
                target_scope="field",
                attach_target_type="field",
            ),
            EffectDefinition(
                effect_id="effect_physical_attack_up_layered",
                effect_name="物攻增加",
                category="stat_modifier",
                polarity="positive",
                display_group="stat_modifier",
                display_priority=410,
                owner_scope="elf",
                target_scope="single_elf",
                attach_target_type="elf",
                stat_modifier_json=dumps_json(
                    {
                        "modifier_type": "stat_stage",
                        "stat": "physical_attack",
                        "value_type": "percent_add",
                        "value_per_layer": 0.1,
                    }
                ),
            ),
            EffectDefinition(
                effect_id="effect_skill_power_combo_cost_layered",
                effect_name="技能层数综合测试",
                category="skill_modifier",
                polarity="positive",
                display_group="skill_modifier",
                display_priority=420,
                owner_scope="elf",
                target_scope="single_elf",
                attach_target_type="elf",
                skill_modifier_json=dumps_json(
                    {
                        "modifier_type": "skill_layer_units",
                        "power_add_per_layer": 10,
                        "hit_count_delta_per_layer": 1,
                        "energy_cost_delta_per_layer": -1,
                    }
                ),
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


def test_modifier_resolver_uses_defense_skill_rule_from_payload() -> None:
    """防御技能减伤规则应进入 damage_reductions。"""
    context = DamageFormulaContext(battle_id="battle_1")

    details = ModifierResolver().resolve_formula_modifiers(
        context,
        {
            "defense_skill_rule": {
                "source_id": "defense_skill",
                "damage_type": "defense_modifier",
                "damage_reduction": 0.7,
            }
        },
    )

    assert context.damage_reductions == [Decimal("0.7")]
    assert details["damage_reductions"]["items"][0]["reduction"] == "0.7"


def test_modifier_resolver_loads_defense_skill_rule_from_db(db_session: Session) -> None:
    """传入 defense_skill_id 时，可从 SkillDefinition.damage_rule_json 读取减伤。"""
    context = DamageFormulaContext(battle_id="battle_1")

    ModifierResolver(db_session).resolve_formula_modifiers(
        context,
        {"defense_skill_id": "defense_skill", "response_attack_success": True},
    )

    assert context.damage_reductions == [Decimal("0.7")]


def test_modifier_resolver_marks_defense_response_unknown_when_flag_missing(
    db_session: Session,
) -> None:
    """防御技能存在应对条件但未确认成功时，不应直接套减伤。"""
    context = DamageFormulaContext(battle_id="battle_1")

    ModifierResolver(db_session).resolve_formula_modifiers(
        context,
        {"defense_skill_id": "defense_skill"},
    )

    assert context.damage_reductions == []
    assert "damage_reduction_active_unknown:0" in context.unknown_factors


def test_modifier_resolver_uses_snapshot_effect_instances(db_session: Session) -> None:
    """历史快照里的防御方状态可被解析为当前事件的减伤来源。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        defender_side="enemy",
        defender_elf_id="elf_a",
        snapshot_payload=[
            {
                "instance_id": "instance_guard",
                "effect_id": "effect_guard",
                "owner_scope": "elf",
                "owner_side": "enemy",
                "owner_elf_id": "elf_a",
                "layers": 1,
            }
        ],
    )

    ModifierResolver(db_session).resolve_formula_modifiers(context, {})

    assert context.damage_reductions == [Decimal("0.5")]


def test_modifier_resolver_adds_dynamic_reduction_from_attacker_effect_layers() -> None:
    """不可接触这类防御技能可按攻击方异常层数追加减伤。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        attacker_side="self",
        attacker_elf_id="elf_self",
        defender_side="enemy",
        defender_elf_id="elf_enemy",
        snapshot_payload=[
            {
                "instance_id": "poison_self",
                "effect_id": "effect_poison",
                "owner_scope": "elf",
                "owner_side": "self",
                "owner_elf_id": "elf_self",
                "layers": 2,
            }
        ],
    )

    details = ModifierResolver().resolve_formula_modifiers(
        context,
        {
            "response_attack_success": True,
            "defense_skill_rule": {
                "source_id": "untouchable",
                "damage_type": "defense_modifier",
                "damage_reduction": 0.5,
                "response_rule": {
                    "target": "attack",
                    "condition": "response_attack_success",
                },
                "dynamic_reduction_rule": {
                    "source_effect_id": "effect_poison",
                    "source_target": "opponent_active_elf",
                    "damage_reduction_per_layer": 0.1,
                },
            },
        },
    )

    assert context.damage_reductions == [Decimal("0.7")]
    item = details["damage_reductions"]["items"][0]
    assert item["reduction"] == "0.7"
    assert item["dynamic_reduction"]["layers"] == "2"
    assert item["dynamic_reduction"]["bonus_reduction"] == "0.2"


def test_modifier_resolver_uses_rain_weather_multiplier(db_session: Session) -> None:
    """雨天应让水系攻击技能进入 1.75 天气倍率。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        skill_element_type="水",
        snapshot_payload=[
            {
                "instance_id": "weather_rain_1",
                "effect_id": "weather_rain",
                "owner_scope": "field",
                "layers": 1,
            }
        ],
    )

    details = ModifierResolver(db_session).resolve_formula_modifiers(context, {})

    assert context.weather_multiplier == Decimal("1.75")
    assert details["weather_multiplier"]["source"] == "weather_skill_modifier"
    assert details["weather_multiplier"]["effect_id"] == "weather_rain"


def test_modifier_resolver_matches_weather_element_aliases(db_session: Session) -> None:
    """天气/状态规则使用中文属性、技能使用英文属性时也应命中。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        skill_element_type="earth",
        snapshot_payload=[
            {
                "instance_id": "weather_sandstorm_1",
                "effect_id": "weather_sandstorm",
                "owner_scope": "field",
                "layers": 1,
            }
        ],
    )

    details = ModifierResolver(db_session).resolve_formula_modifiers(context, {})

    assert context.weather_multiplier == Decimal("1.75")
    assert details["weather_multiplier"]["effect_id"] == "weather_sandstorm"


def test_modifier_resolver_recognizes_blizzard_without_damage_bonus(
    db_session: Session,
) -> None:
    """暴风雪目前只提供回合末冻结结算，不应误加攻击伤害天气倍率。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        skill_element_type="冰",
        snapshot_payload=[
            {
                "instance_id": "weather_blizzard_1",
                "effect_id": "weather_blizzard",
                "owner_scope": "field",
                "layers": 1,
            }
        ],
    )

    details = ModifierResolver(db_session).resolve_formula_modifiers(context, {})

    assert context.weather_multiplier == Decimal("1")
    assert details["weather_multiplier"]["source"] == "weather_effect_no_damage_bonus"


def test_modifier_resolver_uses_physical_attack_up_stat_modifier(
    db_session: Session,
) -> None:
    """力量增效这类物攻+100%状态应进入物理技能能力等级倍率。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        attacker_side="self",
        attacker_elf_id="elf_self",
        defender_side="enemy",
        defender_elf_id="elf_enemy",
        skill_category="physical",
        snapshot_payload=[
            {
                "instance_id": "attack_up_1",
                "effect_id": "effect_physical_attack_up_layered",
                "owner_scope": "elf",
                "owner_side": "self",
                "owner_elf_id": "elf_self",
                "layers": 10,
            }
        ],
    )

    details = ModifierResolver(db_session).resolve_formula_modifiers(context, {})

    assert context.stat_stage_multiplier == Decimal("2")
    assert details["stat_stage_multiplier"]["source"] == "snapshot_stat_modifiers"
    assert details["stat_stage_multiplier"]["items"][0]["effect_id"] == (
        "effect_physical_attack_up_layered"
    )


def test_modifier_resolver_uses_percent_value_per_layer(db_session: Session) -> None:
    """属性修正新规则按 10% 一层解析，同时不影响旧 value 直写规则。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        attacker_side="self",
        attacker_elf_id="elf_self",
        defender_side="enemy",
        defender_elf_id="elf_enemy",
        skill_category="physical",
        snapshot_payload=[
            {
                "instance_id": "attack_layered",
                "effect_id": "effect_physical_attack_up_layered",
                "owner_scope": "elf",
                "owner_side": "self",
                "owner_elf_id": "elf_self",
                "layers": 3,
            }
        ],
    )

    details = ModifierResolver(db_session).resolve_formula_modifiers(context, {})

    assert context.stat_stage_multiplier == Decimal("1.3")
    assert details["stat_stage_multiplier"]["items"][0]["layers"] == "3"
    assert details["stat_stage_multiplier"]["items"][0]["value"] == "0.3"


def test_battle_service_reads_skill_modifier_layer_units(db_session: Session) -> None:
    """技能威力、连击、能耗状态按约定层数单位解析。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        attacker_side="self",
        attacker_elf_id="elf_self",
        defender_side="enemy",
        defender_elf_id="elf_enemy",
        skill_category="physical",
        skill_element_type="火",
        snapshot_payload=[
            {
                "instance_id": "skill_layered",
                "effect_id": "effect_skill_power_combo_cost_layered",
                "owner_scope": "elf",
                "owner_side": "self",
                "owner_elf_id": "elf_self",
                "layers": 2,
            }
        ],
    )

    result = BattleService(db_session)._skill_power_modifier_from_effects(
        context,
        context.snapshot_payload,
        "",
    )

    assert result["flat_power_bonus"] == Decimal("20")
    assert result["hit_count_delta"] == 2
    assert result["energy_cost_delta"] == -2


def test_missing_hp_power_rule_can_cap_effective_power_at_zero(db_session: Session) -> None:
    """Missing-HP negative power rules should honor the configured floor."""
    db_session.add(
        ElfDefinition(
            elf_id="elf_self",
            elf_name="self",
            avatar="",
            element_types_json=dumps_json([]),
            base_hp_talent=100,
            base_physical_attack_talent=100,
            base_physical_defense_talent=100,
            base_magic_attack_talent=100,
            base_magic_defense_talent=100,
            base_speed_talent=100,
        )
    )
    db_session.add(Battle(battle_id="battle_missing_hp", phase="battle", turn_number=1))
    db_session.flush()
    db_session.add(
        BattleElfState(
            state_id="state_missing_hp_self",
            battle_id="battle_missing_hp",
            side="self",
            elf_id="elf_self",
            elf_name="self",
            avatar="",
            panel_stats_json=dumps_json({}),
            current_hp_value=250,
            current_hp_percent=25.0,
            energy=10,
            skill_ids_json=dumps_json([]),
            confirmed_skill_ids_json=dumps_json([]),
            active_effect_instance_ids_json=dumps_json([]),
            is_active_elf=True,
            is_defeated=False,
            manual_override=True,
        )
    )
    db_session.commit()
    context = DamageFormulaContext(
        battle_id="battle_missing_hp",
        attacker_side="self",
        attacker_elf_id="elf_self",
        base_power=40,
    )

    details = ModifierResolver(db_session).resolve_formula_modifiers(
        context,
        {
            "dynamic_power_rule": {
                "missing_hp_percent_step": 5,
                "power_add_per_step": -10,
                "min_power_after_add": 0,
            }
        },
    )

    assert context.flat_power_bonus == Decimal("-40")
    item = details["dynamic_power_rules"][0]
    assert item["capped"] is True


def test_target_normal_switch_condition_ignores_return_to_field(db_session: Session) -> None:
    """Normal switch conditions should ignore return-to-field switch events."""
    db_session.add(Battle(battle_id="battle_switch", phase="battle", turn_number=3))
    db_session.add_all(
        [
            BattleEvent(
                event_id="switch_return",
                battle_id="battle_switch",
                turn_number=3,
                event_type="switch_elf",
                actor_side="enemy",
                actor_elf_id="elf_enemy",
                source="manual_input",
                payload_json=dumps_json({"switch_mode": "return_to_field"}),
            ),
            BattleEvent(
                event_id="switch_normal",
                battle_id="battle_switch",
                turn_number=4,
                event_type="switch_elf",
                actor_side="enemy",
                actor_elf_id="elf_enemy",
                source="manual_input",
                payload_json=dumps_json({"switch_mode": "normal"}),
            ),
        ]
    )
    db_session.commit()
    context = DamageFormulaContext(
        battle_id="battle_switch",
        attacker_side="self",
        defender_side="enemy",
    )

    ModifierResolver(db_session).resolve_formula_modifiers(
        context,
        {
            "turn_number": 3,
            "dynamic_power_rule": {
                "condition": "target_normal_switched_this_turn",
                "power_add": 100,
            },
        },
    )
    assert context.flat_power_bonus == Decimal("0")

    ModifierResolver(db_session).resolve_formula_modifiers(
        context,
        {
            "turn_number": 4,
            "dynamic_power_rule": {
                "condition": "target_normal_switched_this_turn",
                "power_add": 100,
            },
        },
    )
    assert context.flat_power_bonus == Decimal("100")


def test_response_resolver_marks_unknown_when_success_flag_missing() -> None:
    """应对分支存在但成功与否未知时，只写 unknown，不改变倍率。"""
    context = DamageFormulaContext(battle_id="battle_1")

    details = ResponseResolver().resolve_response_modifiers(
        context,
        {"response_rule": {"target": "attack", "success_multiplier": 3}},
    )

    assert context.response_multiplier == Decimal("1")
    assert "response_success_unknown" in context.unknown_factors
    assert details["response_multiplier"]["source"] == "rule_branch_unknown"
