"""状态伤害计算测试。"""

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext


def test_status_damage_calculates_burn_with_type_multiplier() -> None:
    """灼烧按最大生命、层数和火系克制倍率计算。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        formula_type="status",
        effect_id="effect_burn",
        effect_layers=10,
        defender_max_hp=500,
        type_multiplier=2,
    )

    result = DamageCalculator().calculate(context)

    assert result.status == "calculated"
    assert result.damage_value == 200
    assert result.explanation["after_settlement"] == {"layer_change": "halve_floor"}


def test_status_damage_calculates_poison_mark() -> None:
    """中毒印记每层造成 3% 最大生命毒系伤害。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        formula_type="status",
        effect_id="effect_poison_mark",
        effect_layers=3,
        defender_max_hp=333,
        type_multiplier=1,
    )

    result = DamageCalculator().calculate(context)

    assert result.status == "calculated"
    assert result.damage_value == 29


def test_status_damage_calculates_leech_and_secondary_heal() -> None:
    """寄生造成真实伤害并生成回血二级事件。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        formula_type="status",
        effect_id="effect_leech_seed",
        defender_max_hp=400,
    )

    result = DamageCalculator().calculate(context)

    assert result.status == "calculated"
    assert result.damage_value == 24
    assert result.secondary_events == [
        {"type": "heal", "target": "source_or_opponent", "value": 24}
    ]


def test_status_damage_checks_freeze_threshold() -> None:
    """冻结在生命百分比小于等于层数 * 5% 时触发力竭。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        formula_type="status",
        effect_id="effect_freeze",
        effect_layers=4,
        defender_hp_percent=20,
    )

    result = DamageCalculator().calculate(context)

    assert result.status == "calculated"
    assert result.damage_value is None
    assert result.explanation["threshold_percent"] == "20"
    assert result.explanation["defeated_by_freeze"] is True


def test_status_damage_returns_unavailable_without_max_hp() -> None:
    """百分比状态伤害缺少最大生命时不得假算。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        formula_type="status",
        effect_id="effect_thorn_mark",
        effect_layers=2,
    )

    result = DamageCalculator().calculate(context)

    assert result.status == "formula_unavailable"
    assert "defender_max_hp" in result.missing_parts
