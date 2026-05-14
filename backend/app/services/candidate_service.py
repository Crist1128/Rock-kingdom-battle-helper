"""
候选配置生成服务模块。

本模块负责敌方候选配置的枚举、落库和摘要查询。第一阶段只生成：
性格 × 个体资质分布 × 面板属性。技能组不做笛卡尔展开，只把可学习技能池
保存到 possible_skill_ids_json，后续通过战斗事件逐步确认。
"""

from dataclasses import dataclass
from itertools import combinations, product
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.calculation.stat_calculator import (
    BaseTalentBlock,
    IndividualTalentDistribution,
    NatureRule,
    StatCalculator,
)
from app.core.enums import StatKey
from app.models.candidate import BuildCandidate
from app.models.static import ElfDefinition, ElfLearnableSkill, NatureDefinition
from app.schemas.candidate import CandidateSummaryOut
from app.utils.json import dumps_json

# 六维属性键列表，用于生成个体资质和性格组合。
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

    一个种子只包含性格和个体资质分布。完整候选还需要结合精灵种族资质
    计算最终面板属性，并补充可学习技能池后才能落库。
    """

    nature_id: str
    individual_talent_distribution: IndividualTalentDistribution


class CandidateGenerator:
    """
    敌方候选配置种子生成器。

    按需求枚举：
    - 个体资质：1-3 个维度有值，每个有值维度为 7-10，其余为 0。
    - 性格：由数据库 nature_definition 提供，通常为 30 种。
    """

    def generate_individual_talent_distributions(self) -> list[IndividualTalentDistribution]:
        """生成所有可能的个体资质分布组合。"""
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
        """
        生成内存性格规则。

        该方法保留给测试和开发使用。正式候选落库时应使用数据库中的
        nature_definition，避免候选 nature_id 与外键不一致。
        """
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
        """计算理论候选数量。"""
        distribution_count = len(self.generate_individual_talent_distributions())
        nature_count = len(self.generate_nature_rules())
        return distribution_count * nature_count


class CandidateService:
    """
    敌方候选配置服务。

    该服务是准备阶段与推算阶段的桥梁。准备阶段根据敌方 elf_id 生成候选，
    推算阶段会读取并更新这些候选的 match_score、confidence 和 is_excluded。
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.generator = CandidateGenerator()

    def generate_for_enemy_elf(
        self,
        battle_id: str,
        elf_id: str,
        *,
        replace_existing: bool = True,
        commit: bool = True,
    ) -> int:
        """
        为指定敌方精灵生成并落库候选配置。

        Args:
            battle_id: 战斗 ID。
            elf_id: 敌方精灵 ID。
            replace_existing: 是否先删除同战斗同精灵旧候选。
            commit: 是否在方法内提交事务。

        Returns:
            int: 本次生成的候选数量。
        """
        elf = self.db.get(ElfDefinition, elf_id)
        if elf is None or elf.deleted_at is not None:
            raise ValueError(f"精灵不存在：{elf_id}")

        nature_rules = self._load_nature_rules()
        distributions = self.generator.generate_individual_talent_distributions()
        possible_skill_ids = self._load_learnable_skill_ids(elf_id)
        base = self._elf_to_base_talent_block(elf)

        if replace_existing:
            self.db.execute(
                delete(BuildCandidate).where(
                    BuildCandidate.battle_id == battle_id,
                    BuildCandidate.elf_id == elf_id,
                )
            )

        count = 0
        buffer: list[BuildCandidate] = []
        possible_skill_ids_json = dumps_json(possible_skill_ids)
        confirmed_skill_ids_json = dumps_json([])

        for nature in nature_rules:
            for distribution in distributions:
                panel = StatCalculator.calculate_panel_stats(base, distribution, nature)
                buffer.append(
                    BuildCandidate(
                        candidate_id=f"candidate_{uuid4().hex}",
                        battle_id=battle_id,
                        side="enemy",
                        elf_id=elf_id,
                        nature_id=nature.nature_id,
                        individual_talent_distribution_json=dumps_json(distribution),
                        final_hp=panel.hp,
                        final_physical_attack=panel.physical_attack,
                        final_physical_defense=panel.physical_defense,
                        final_magic_attack=panel.magic_attack,
                        final_magic_defense=panel.magic_defense,
                        final_speed=panel.speed,
                        possible_skill_ids_json=possible_skill_ids_json,
                        confirmed_skill_ids_json=confirmed_skill_ids_json,
                        match_score=0.0,
                        confidence=0.0,
                        is_excluded=False,
                    )
                )
                count += 1

                # 大量候选一次性 add 会占用较多内存，分批 flush 更稳妥。
                if len(buffer) >= 1000:
                    self.db.add_all(buffer)
                    self.db.flush()
                    buffer.clear()

        if buffer:
            self.db.add_all(buffer)
            self.db.flush()

        if commit:
            self.db.commit()
        return count

    def summarize(self, battle_id: str, elf_id: str) -> CandidateSummaryOut:
        """获取指定敌方精灵候选摘要。"""
        total_count = self.db.scalar(
            select(func.count()).select_from(BuildCandidate).where(
                BuildCandidate.battle_id == battle_id,
                BuildCandidate.elf_id == elf_id,
            )
        ) or 0
        active_count = self.db.scalar(
            select(func.count()).select_from(BuildCandidate).where(
                BuildCandidate.battle_id == battle_id,
                BuildCandidate.elf_id == elf_id,
                BuildCandidate.is_excluded.is_(False),
            )
        ) or 0
        min_speed = self.db.scalar(
            select(func.min(BuildCandidate.final_speed)).where(
                BuildCandidate.battle_id == battle_id,
                BuildCandidate.elf_id == elf_id,
                BuildCandidate.is_excluded.is_(False),
            )
        )
        max_speed = self.db.scalar(
            select(func.max(BuildCandidate.final_speed)).where(
                BuildCandidate.battle_id == battle_id,
                BuildCandidate.elf_id == elf_id,
                BuildCandidate.is_excluded.is_(False),
            )
        )
        top_confidence = self.db.scalar(
            select(func.max(BuildCandidate.confidence)).where(
                BuildCandidate.battle_id == battle_id,
                BuildCandidate.elf_id == elf_id,
                BuildCandidate.is_excluded.is_(False),
            )
        )
        return CandidateSummaryOut(
            battle_id=battle_id,
            elf_id=elf_id,
            total_count=total_count,
            active_count=active_count,
            excluded_count=total_count - active_count,
            min_speed=min_speed,
            max_speed=max_speed,
            top_confidence=top_confidence,
            formula_status="formula_unavailable",
        )

    def list_candidates(
        self,
        battle_id: str,
        elf_id: str,
        *,
        include_excluded: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BuildCandidate]:
        """分页查看候选配置明细。"""
        stmt = select(BuildCandidate).where(
            BuildCandidate.battle_id == battle_id,
            BuildCandidate.elf_id == elf_id,
        )
        if not include_excluded:
            stmt = stmt.where(BuildCandidate.is_excluded.is_(False))
        stmt = (
            stmt.order_by(BuildCandidate.confidence.desc(), BuildCandidate.final_speed)
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt).all())

    def _load_nature_rules(self) -> list[NatureRule]:
        """
        从 nature_definition 加载性格规则。

        候选表对 nature_id 有外键约束，因此这里必须使用数据库已有性格。
        """
        rows = self.db.scalars(
            select(NatureDefinition).where(NatureDefinition.deleted_at.is_(None))
        ).all()
        if not rows:
            raise ValueError("nature_definition 为空，请先导入 30 个性格定义")
        return [
            NatureRule(
                nature_id=row.nature_id,
                positive_stat=StatKey(row.positive_stat),
                negative_stat=StatKey(row.negative_stat),
            )
            for row in rows
        ]

    def _load_learnable_skill_ids(self, elf_id: str) -> list[str]:
        """读取精灵可学习技能池。没有数据时返回空列表。"""
        return list(
            self.db.scalars(
                select(ElfLearnableSkill.skill_id)
                .where(ElfLearnableSkill.elf_id == elf_id)
                .order_by(ElfLearnableSkill.skill_id)
            ).all()
        )

    @staticmethod
    def _elf_to_base_talent_block(elf: ElfDefinition) -> BaseTalentBlock:
        """从精灵定义提取六维种族资质。"""
        return BaseTalentBlock(
            hp=elf.base_hp_talent,
            physical_attack=elf.base_physical_attack_talent,
            physical_defense=elf.base_physical_defense_talent,
            magic_attack=elf.base_magic_attack_talent,
            magic_defense=elf.base_magic_defense_talent,
            speed=elf.base_speed_talent,
        )
