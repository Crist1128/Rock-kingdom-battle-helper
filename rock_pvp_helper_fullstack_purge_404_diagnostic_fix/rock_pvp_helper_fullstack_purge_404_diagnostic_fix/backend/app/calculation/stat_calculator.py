"""
面板属性计算模块。

本模块提供 PVP 面板属性的计算功能，包括：
- 六维属性计算（生命、物攻、物防、魔攻、魔防、速度）
- 性格修正应用
- 取整规则处理

计算规则基于需求文档中的 PVP 简化公式：
- 等级固定 60
- 生命成长值 100，非生命成长值 50
- 生命属性四舍五入，非生命属性向上取整
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from app.core.enums import StatKey


class BaseTalentBlock(BaseModel):
    """
    种族资质数据块。

    存储精灵的六维种族资质值，用于面板属性计算。

    Attributes:
        hp: 生命种族资质
        physical_attack: 物攻种族资质
        physical_defense: 物防种族资质
        magic_attack: 魔攻种族资质
        magic_defense: 魔防种族资质
        speed: 速度种族资质
    """
    hp: int
    physical_attack: int
    physical_defense: int
    magic_attack: int
    magic_defense: int
    speed: int


class IndividualTalentDistribution(BaseModel):
    """
    个体资质分布数据块。

    存储精灵的六维个体资质值，默认所有维度为 0。
    实际培养时，1-3 个维度有值（7-10），其余为 0。

    Attributes:
        hp: 生命个体资质，默认 0
        physical_attack: 物攻个体资质，默认 0
        physical_defense: 物防个体资质，默认 0
        magic_attack: 魔攻个体资质，默认 0
        magic_defense: 魔防个体资质，默认 0
        speed: 速度个体资质，默认 0
    """
    hp: int = 0
    physical_attack: int = 0
    physical_defense: int = 0
    magic_attack: int = 0
    magic_defense: int = 0
    speed: int = 0


class PanelStats(BaseModel):
    """
    面板属性数据块。

    存储计算后的最终六维面板属性值。

    Attributes:
        hp: 最终生命
        physical_attack: 最终物攻
        physical_defense: 最终物防
        magic_attack: 最终魔攻
        magic_defense: 最终魔防
        speed: 最终速度
    """
    hp: int
    physical_attack: int
    physical_defense: int
    magic_attack: int
    magic_defense: int
    speed: int


@dataclass(frozen=True)
class NatureRule:
    """
    性格规则数据类。

    定义性格对属性的修正规则：
    - 正面修正属性 +20%（默认倍率 1.2）
    - 负面修正属性 -10%（默认倍率 0.9）
    - 其他属性不变（默认倍率 1.0）

    Attributes:
        nature_id: 性格标识
        positive_stat: 正面修正属性键
        negative_stat: 负面修正属性键
        positive_multiplier: 正面修正倍率，默认 1.2
        negative_multiplier: 负面修正倍率，默认 0.9
        neutral_multiplier: 中性修正倍率，默认 1.0
    """
    nature_id: str
    positive_stat: StatKey
    negative_stat: StatKey
    positive_multiplier: Decimal = Decimal("1.2")
    negative_multiplier: Decimal = Decimal("0.9")
    neutral_multiplier: Decimal = Decimal("1.0")

    def multiplier_for(self, stat_key: StatKey) -> Decimal:
        """
        获取指定属性的修正倍率。

        Args:
            stat_key: 属性键

        Returns:
            Decimal: 该属性的修正倍率
        """
        if stat_key == self.positive_stat:
            return self.positive_multiplier
        if stat_key == self.negative_stat:
            return self.negative_multiplier
        return self.neutral_multiplier


class StatCalculator:
    """
    PVP 面板属性计算器。

    根据种族资质、个体资质和性格计算最终面板属性。
    使用 PVP 简化公式，等级固定 60，成长值固定（生命 100，非生命 50）。

    说明：需求中生命为"四舍五入"。这里采用 ROUND_HALF_UP，避免 Python round 的 bankers rounding。

    Example:
        calculator = StatCalculator()
        panel_stats = calculator.calculate_panel_stats(base, individual, nature)
    """

    @staticmethod
    def calculate_panel_stats(
        base: BaseTalentBlock,
        individual: IndividualTalentDistribution,
        nature: NatureRule,
    ) -> PanelStats:
        """
        计算完整六维面板属性。

        Args:
            base: 种族资质数据块
            individual: 个体资质分布数据块
            nature: 性格规则

        Returns:
            PanelStats: 计算后的六维面板属性
        """
        return PanelStats(
            hp=StatCalculator.calculate_hp(
                base.hp,
                individual.hp,
                nature.multiplier_for(StatKey.HP),
            ),
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
        """
        计算生命属性。

        公式：round((70 + 1.7 * 种族资质 + 0.85 * 个体资质) * 性格倍率 + 100)

        Args:
            base_talent: 生命种族资质
            individual_talent: 生命个体资质
            nature_multiplier: 性格修正倍率

        Returns:
            int: 最终生命属性值（四舍五入）
        """
        value = (Decimal("70") + Decimal("1.7") * base_talent + Decimal("0.85") * individual_talent)
        value = value * nature_multiplier + Decimal("100")
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def calculate_non_hp(
        base_talent: int,
        individual_talent: int,
        nature_multiplier: Decimal,
    ) -> int:
        """
        计算非生命属性（物攻、物防、魔攻、魔防、速度）。

        公式：ceil((10 + 1.1 * 种族资质 + 0.55 * 个体资质) * 性格倍率 + 50)

        Args:
            base_talent: 种族资质
            individual_talent: 个体资质
            nature_multiplier: 性格修正倍率

        Returns:
            int: 最终属性值（向上取整）
        """
        value = (Decimal("10") + Decimal("1.1") * base_talent + Decimal("0.55") * individual_talent)
        value = value * nature_multiplier + Decimal("50")
        return int(value.quantize(Decimal("1"), rounding=ROUND_CEILING))
