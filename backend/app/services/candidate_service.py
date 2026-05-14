"""
候选配置生成服务模块。

本模块提供敌方候选配置的生成逻辑，包括：
- 生成所有可能的个体资质分布组合
- 生成所有可能的性格组合
- 计算候选配置数量

候选配置用于敌方精灵配置推算，通过伤害事件不断收敛。
"""

from dataclasses import dataclass
from itertools import combinations, product

from app.calculation.stat_calculator import IndividualTalentDistribution, NatureRule, StatCalculator
from app.core.enums import StatKey

# 六维属性键列表，用于生成个体资质和性格组合
STAT_KEYS = [
    StatKey.HP,
    StatKey.PHYSICAL_ATTACK,
    StatKey.PHYSICAL_DEFENSE,
    StatKey.MAGIC_ATTACK,
    StatKey.MAGIC_DEFENSE,
    StatKey.SPEED,
]


@dataclass(frozen=True)
class CandidateSeed:
    """
    候选配置种子。

    候选配置的基础组成部分，包含性格和个体资质分布。
    用于生成完整的候选配置。

    Attributes:
        nature_id: 性格标识
        individual_talent_distribution: 个体资质分布
    """
    nature_id: str
    individual_talent_distribution: IndividualTalentDistribution


class CandidateGenerator:
    """
    敌方候选配置生成器。

    为敌方精灵生成所有可能的配置组合，包括：
    - 性格：六维中选一个正面、一个不同的负面，共 30 种
    - 个体资质：1-3 个维度有值（7-10），其余为 0，约 5000+ 种

    当前版本只生成性格 + 个体资质组合种子；
    落库和权重计算后续接入 BuildCandidate。

    Example:
        generator = CandidateGenerator()
        distributions = generator.generate_individual_talent_distributions()
        nature_rules = generator.generate_nature_rules()
        count = generator.generate_candidate_count()
    """

    def generate_individual_talent_distributions(self) -> list[IndividualTalentDistribution]:
        """
        生成所有可能的个体资质分布组合。

        根据规则，单只精灵有 1-3 个维度存在个体资质，数值范围为 7-10，
        其余维度为 0。本方法枚举所有可能的组合。

        Returns:
            list[IndividualTalentDistribution]: 所有可能的个体资质分布列表
        """
        results: list[IndividualTalentDistribution] = []
        # 枚举有值的维度数量：1、2 或 3 个维度
        for count in (1, 2, 3):
            # 从六维中选择 count 个维度有值
            for keys in combinations(STAT_KEYS, count):
                # 每个有值维度的数值范围是 7-10
                for values in product(range(7, 11), repeat=count):
                    # 初始化所有维度为 0
                    item = {key.value: 0 for key in STAT_KEYS}
                    # 设置选中的维度的值
                    for key, value in zip(keys, values, strict=True):
                        item[key.value] = value
                    # 创建分布对象并添加到结果
                    results.append(IndividualTalentDistribution(**item))
        return results

    def generate_nature_rules(self) -> list[NatureRule]:
        """
        生成所有可能的性格规则组合。

        根据规则，性格有一个正面修正属性（+20%）和一个负面修正属性（-10%），
        两者不能相同。本方法枚举所有 6 × 5 = 30 种组合。

        Returns:
            list[NatureRule]: 所有可能的性格规则列表
        """
        rules: list[NatureRule] = []
        # 枚举所有正面属性
        for positive in STAT_KEYS:
            # 枚举所有负面属性，不能与正面相同
            for negative in STAT_KEYS:
                if positive == negative:
                    continue
                # 创建性格规则
                rules.append(
                    NatureRule(
                        nature_id=f"{positive.value}_plus_{negative.value}_minus",
                        positive_stat=positive,
                        negative_stat=negative,
                    )
                )
        return rules

    def generate_candidate_count(self) -> int:
        """
        计算候选配置的总数量。

        计算所有可能的性格 × 个体资质组合数量。

        Returns:
            int: 候选配置总数量
        """
        return len(self.generate_individual_talent_distributions()) * len(self.generate_nature_rules())
