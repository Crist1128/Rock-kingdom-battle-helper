"""星陨印记伤害计算测试。"""

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext, PanelStats


def _context(**overrides: object) -> DamageFormulaContext:
    """构造星陨计算默认上下文。"""
    data: dict[str, object] = {
        "battle_id": "battle_1",
        "damage_event_id": "damage_starfall_1",
        "formula_type": "starfall",
        "effect_id": "effect_starfall_mark",
        "effect_layers": 10,
        "trigger_skill_id": "fire_skill",
        "trigger_skill_element_type": "火",
        "trigger_skill_category": "physical",
        "type_multiplier": 2,
        "attacker_panel_stats": PanelStats(
            hp=300,
            physical_attack=200,
            physical_defense=100,
            magic_attack=120,
            magic_defense=100,
            speed=100,
        ),
        "defender_panel_stats": PanelStats(
            hp=300,
            physical_attack=100,
            physical_defense=100,
            magic_attack=100,
            magic_defense=150,
            speed=100,
        ),
    }
    data.update(overrides)
    return DamageFormulaContext(**data)


def test_starfall_damage_uses_illusion_type_multiplier() -> None:
    """星陨按幻系克制倍率结算，而不是继承触发技能的系别倍率。"""
    result = DamageCalculator().calculate(_context(type_multiplier=2))

    assert result.status == "calculated"
    assert result.damage_value == 1140
    assert result.explanation["starfall_element_type"] == "幻"
    assert result.explanation["uses_type_effectiveness"] is True
    assert result.explanation["type_multiplier"] == "2"
    assert result.explanation["affected_by_stab"] is False


def test_starfall_damage_selects_magic_stats_from_trigger_category() -> None:
    """魔攻触发技能应让星陨使用魔攻/魔防。"""
    result = DamageCalculator().calculate(
        _context(trigger_skill_category="magic", effect_layers=5, type_multiplier=1)
    )

    assert result.status == "calculated"
    assert result.damage_value == 87
    assert result.explanation["trigger_skill_category"] == "magic"
    assert result.explanation["offense_stat"] == "120"
    assert result.explanation["defense_stat"] == "150"


def test_starfall_damage_does_not_trigger_on_illusion_skill() -> None:
    """幻系攻击技能本身不会触发星陨。"""
    result = DamageCalculator().calculate(_context(trigger_skill_element_type="幻"))

    assert result.status == "not_triggered"
    assert result.damage_value is None


def test_starfall_damage_applies_damage_reduction() -> None:
    """防御减伤仍应作用于星陨。"""
    result = DamageCalculator().calculate(_context(type_multiplier=2, damage_reductions=[0.5]))

    assert result.status == "calculated"
    assert result.damage_value == 570
    assert result.explanation["reduction_product"] == "0.5"


def test_starfall_damage_returns_unavailable_without_trigger_category() -> None:
    """缺少触发技能类别时不能猜测物理或魔法分支。"""
    result = DamageCalculator().calculate(
        _context(trigger_skill_category=None, skill_category=None)
    )

    assert result.status == "formula_unavailable"
    assert "trigger_skill_category" in result.missing_parts
