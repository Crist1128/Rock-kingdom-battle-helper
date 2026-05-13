from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from pydantic import BaseModel

from app.core.enums import StatKey


class BaseTalentBlock(BaseModel):
    hp: int
    physical_attack: int
    physical_defense: int
    magic_attack: int
    magic_defense: int
    speed: int


class IndividualTalentDistribution(BaseModel):
    hp: int = 0
    physical_attack: int = 0
    physical_defense: int = 0
    magic_attack: int = 0
    magic_defense: int = 0
    speed: int = 0


class PanelStats(BaseModel):
    hp: int
    physical_attack: int
    physical_defense: int
    magic_attack: int
    magic_defense: int
    speed: int


@dataclass(frozen=True)
class NatureRule:
    nature_id: str
    positive_stat: StatKey
    negative_stat: StatKey
    positive_multiplier: Decimal = Decimal("1.2")
    negative_multiplier: Decimal = Decimal("0.9")
    neutral_multiplier: Decimal = Decimal("1.0")

    def multiplier_for(self, stat_key: StatKey) -> Decimal:
        if stat_key == self.positive_stat:
            return self.positive_multiplier
        if stat_key == self.negative_stat:
            return self.negative_multiplier
        return self.neutral_multiplier


class StatCalculator:
    """PVP 面板属性计算器。

    说明：需求中生命为“四舍五入”。这里采用 ROUND_HALF_UP，避免 Python round 的 bankers rounding。
    """

    @staticmethod
    def calculate_panel_stats(
        base: BaseTalentBlock,
        individual: IndividualTalentDistribution,
        nature: NatureRule,
    ) -> PanelStats:
        return PanelStats(
            hp=StatCalculator.calculate_hp(base.hp, individual.hp, nature.multiplier_for(StatKey.HP)),
            physical_attack=StatCalculator.calculate_non_hp(
                base.physical_attack,
                individual.physical_attack,
                nature.multiplier_for(StatKey.PHYSICAL_ATTACK),
            ),
            physical_defense=StatCalculator.calculate_non_hp(
                base.physical_defense,
                individual.physical_defense,
                nature.multiplier_for(StatKey.PHYSICAL_DEFENSE),
            ),
            magic_attack=StatCalculator.calculate_non_hp(
                base.magic_attack,
                individual.magic_attack,
                nature.multiplier_for(StatKey.MAGIC_ATTACK),
            ),
            magic_defense=StatCalculator.calculate_non_hp(
                base.magic_defense,
                individual.magic_defense,
                nature.multiplier_for(StatKey.MAGIC_DEFENSE),
            ),
            speed=StatCalculator.calculate_non_hp(
                base.speed,
                individual.speed,
                nature.multiplier_for(StatKey.SPEED),
            ),
        )

    @staticmethod
    def calculate_hp(base_talent: int, individual_talent: int, nature_multiplier: Decimal) -> int:
        value = (Decimal("70") + Decimal("1.7") * base_talent + Decimal("0.85") * individual_talent)
        value = value * nature_multiplier + Decimal("100")
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def calculate_non_hp(base_talent: int, individual_talent: int, nature_multiplier: Decimal) -> int:
        value = (Decimal("10") + Decimal("1.1") * base_talent + Decimal("0.55") * individual_talent)
        value = value * nature_multiplier + Decimal("50")
        return int(value.quantize(Decimal("1"), rounding=ROUND_CEILING))
