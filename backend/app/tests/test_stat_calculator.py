"""
面板属性计算测试模块。

本模块包含 StatCalculator 的单元测试，验证 PVP 面板属性计算的正确性。
"""

from decimal import Decimal

from app.calculation.stat_calculator import (
    BaseTalentBlock,
    IndividualTalentDistribution,
    NatureRule,
    StatCalculator,
)
from app.core.enums import StatKey


def test_panel_stat_formula_uses_pvp_simplified_rules() -> None:
    """
    测试 PVP 简化公式的面板属性计算。

    验证点：
    1. 生命属性使用四舍五入
    2. 非生命属性使用标准四舍五入
    3. 性格修正正确应用（正面 +20%，负面 -10%）
    4. 公式计算符合需求文档规范

    测试数据：
    - 种族资质：全 100
    - 个体资质：生命 10、物攻 10、速度 10，其余 0
    - 性格：物攻 +20%（正面），魔攻 -10%（负面）

    预期结果：
    - 生命：round((70 + 170 + 51) * 1) + 100 = 391
    - 物攻：round(round(10 + 110 + 33) * 1.2) + 50 = 234
    - 魔攻：round(round(10 + 110 + 0) * 0.9) + 50 = 158
    - 速度：round(round(10 + 110 + 33) * 1) + 50 = 203
    """
    # 准备测试数据
    base = BaseTalentBlock(
        hp=100,
        physical_attack=100,
        physical_defense=100,
        magic_attack=100,
        magic_defense=100,
        speed=100,
    )

    individual = IndividualTalentDistribution(
        hp=10,
        physical_attack=10,
        speed=10
        # 其他维度默认为 0
    )

    nature = NatureRule(
        nature_id="test",
        positive_stat=StatKey.PHYSICAL_ATTACK,
        negative_stat=StatKey.MAGIC_ATTACK,
        positive_multiplier=Decimal("1.2"),
        negative_multiplier=Decimal("0.9"),
    )

    # 执行计算
    result = StatCalculator.calculate_panel_stats(base, individual, nature)

    # 验证结果
    assert result.hp == 391  # round((70 + 170 + 51) * 1) + 100
    assert result.physical_attack == 234  # round(round(10 + 110 + 33) * 1.2) + 50
    assert result.magic_attack == 158  # round(round(10 + 110 + 0) * 0.9) + 50
    assert result.speed == 203  # round(round(10 + 110 + 33) * 1) + 50


def test_panel_stat_formula_matches_real_fire_god_case() -> None:
    """火神真实测试数据：前端输入个体资质 8 时，公式中按 8 * 6 带入。"""
    base = BaseTalentBlock(
        hp=117,
        physical_attack=139,
        physical_defense=94,
        magic_attack=61,
        magic_defense=72,
        speed=130,
    )
    individual = IndividualTalentDistribution(
        hp=8,
        physical_attack=8,
        speed=8,
    )
    nature = NatureRule(
        nature_id="physical_attack_plus_magic_attack_minus",
        positive_stat=StatKey.PHYSICAL_ATTACK,
        negative_stat=StatKey.MAGIC_ATTACK,
        positive_multiplier=Decimal("1.2"),
        negative_multiplier=Decimal("0.9"),
    )

    result = StatCalculator.calculate_panel_stats(base, individual, nature)

    assert result.hp == 410
    assert result.physical_attack == 277
    assert result.physical_defense == 163
    assert result.magic_attack == 119
    assert result.magic_defense == 139
    assert result.speed == 229


def test_panel_stat_formula_matches_real_dragon_breath_pal_case() -> None:
    """龙息帕尔真实测试数据：非生命需要先基础段取整，再性格修正取整。"""
    base = BaseTalentBlock(
        hp=130,
        physical_attack=127,
        physical_defense=131,
        magic_attack=57,
        magic_defense=87,
        speed=100,
    )
    individual = IndividualTalentDistribution(
        hp=10,
        physical_attack=10,
        speed=10,
    )
    nature = NatureRule(
        nature_id="physical_attack_plus_magic_attack_minus",
        positive_stat=StatKey.PHYSICAL_ATTACK,
        negative_stat=StatKey.MAGIC_ATTACK,
        positive_multiplier=Decimal("1.2"),
        negative_multiplier=Decimal("0.9"),
    )

    result = StatCalculator.calculate_panel_stats(base, individual, nature)

    assert result.hp == 442
    assert result.physical_attack == 270
    assert result.physical_defense == 204
    assert result.magic_attack == 116
    assert result.magic_defense == 156
    assert result.speed == 203
