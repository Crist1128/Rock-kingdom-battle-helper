from decimal import Decimal

from app.calculation.stat_calculator import (
    BaseTalentBlock,
    IndividualTalentDistribution,
    NatureRule,
    StatCalculator,
)
from app.core.enums import StatKey


def test_panel_stat_formula_uses_pvp_simplified_rules() -> None:
    base = BaseTalentBlock(
        hp=100,
        physical_attack=100,
        physical_defense=100,
        magic_attack=100,
        magic_defense=100,
        speed=100,
    )
    individual = IndividualTalentDistribution(hp=10, physical_attack=10, speed=10)
    nature = NatureRule(
        nature_id="test",
        positive_stat=StatKey.PHYSICAL_ATTACK,
        negative_stat=StatKey.MAGIC_ATTACK,
        positive_multiplier=Decimal("1.2"),
        negative_multiplier=Decimal("0.9"),
    )

    result = StatCalculator.calculate_panel_stats(base, individual, nature)

    assert result.hp == 349  # round((70 + 170 + 8.5) * 1 + 100)
    assert result.physical_attack == 201  # ceil((10 + 110 + 5.5) * 1.2 + 50)
    assert result.magic_attack == 158  # ceil((10 + 110 + 0) * 0.9 + 50)
    assert result.speed == 176  # ceil((10 + 110 + 5.5) * 1 + 50)
