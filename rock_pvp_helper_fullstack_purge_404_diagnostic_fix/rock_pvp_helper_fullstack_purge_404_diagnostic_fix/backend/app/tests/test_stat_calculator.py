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
    2. 非生命属性使用向上取整
    3. 性格修正正确应用（正面 +20%，负面 -10%）
    4. 公式计算符合需求文档规范

    测试数据：
    - 种族资质：全 100
    - 个体资质：生命 10、物攻 10、速度 10，其余 0
    - 性格：物攻 +20%（正面），魔攻 -10%（负面）

    预期结果：
    - 生命：round((70 + 170 + 8.5) * 1 + 100) = 349
    - 物攻：ceil((10 + 110 + 5.5) * 1.2 + 50) = 201
    - 魔攻：ceil((10 + 110 + 0) * 0.9 + 50) = 158
    - 速度：ceil((10 + 110 + 5.5) * 1 + 50) = 176
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
    assert result.hp == 349  # round((70 + 170 + 8.5) * 1 + 100)
    assert result.physical_attack == 201  # ceil((10 + 110 + 5.5) * 1.2 + 50)
    assert result.magic_attack == 158  # ceil((10 + 110 + 0) * 0.9 + 50)
    assert result.speed == 176  # ceil((10 + 110 + 5.5) * 1 + 50)
