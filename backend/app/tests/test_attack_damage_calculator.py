"""普通攻击伤害计算测试。"""

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext, PanelStats


def test_attack_damage_calculator_calculates_basic_physical_damage() -> None:
    """验证最小普通物理伤害公式：floor((A/D * 37/41) * power)。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        damage_event_id="damage_1",
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
        skill_category="physical",
        base_power=50,
    )

    result = DamageCalculator().calculate(context)

    assert result.status == "calculated"
    assert result.damage_value == 90
    assert result.explanation["single_damage"] == 90


def test_attack_damage_calculator_returns_unavailable_when_context_missing() -> None:
    """上下文缺少面板或威力时不得使用临时假公式。"""
    context = DamageFormulaContext(battle_id="battle_1", damage_event_id="damage_1")

    result = DamageCalculator().calculate(context)

    assert result.status == "formula_unavailable"
    assert "attacker_panel_stats" in result.missing_parts
    assert "defender_panel_stats" in result.missing_parts
    assert "base_power_or_display_power" in result.missing_parts
