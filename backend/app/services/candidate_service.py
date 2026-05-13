from dataclasses import dataclass
from itertools import combinations, product

from app.calculation.stat_calculator import IndividualTalentDistribution, NatureRule, StatCalculator
from app.core.enums import StatKey

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
    nature_id: str
    individual_talent_distribution: IndividualTalentDistribution


class CandidateGenerator:
    """敌方候选生成器骨架。

    当前只生成性格 + 个体资质组合种子；落库和权重后续接入 BuildCandidate。
    """

    def generate_individual_talent_distributions(self) -> list[IndividualTalentDistribution]:
        results: list[IndividualTalentDistribution] = []
        for count in (1, 2, 3):
            for keys in combinations(STAT_KEYS, count):
                for values in product(range(7, 11), repeat=count):
                    item = {key.value: 0 for key in STAT_KEYS}
                    for key, value in zip(keys, values, strict=True):
                        item[key.value] = value
                    results.append(IndividualTalentDistribution(**item))
        return results

    def generate_nature_rules(self) -> list[NatureRule]:
        rules: list[NatureRule] = []
        for positive in STAT_KEYS:
            for negative in STAT_KEYS:
                if positive == negative:
                    continue
                rules.append(
                    NatureRule(
                        nature_id=f"{positive.value}_plus_{negative.value}_minus",
                        positive_stat=positive,
                        negative_stat=negative,
                    )
                )
        return rules

    def generate_candidate_count(self) -> int:
        return len(self.generate_individual_talent_distributions()) * len(self.generate_nature_rules())
