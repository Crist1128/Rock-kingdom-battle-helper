"""
己方精灵配置服务。

本服务负责创建、查询玩家提前录入的己方完整配置。准备阶段录入己方阵容时，
BattleService 会从这里读取确定的面板属性和技能槽，复制到 BattleElfState。
"""

from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.calculation.stat_calculator import (
    BaseTalentBlock,
    IndividualTalentDistribution,
    NatureRule,
    StatCalculator,
)
from app.core.enums import StatKey
from app.models.static import (
    ElfDefinition,
    NatureDefinition,
    PlayerElfBuild,
    PlayerElfBuildSkill,
    SkillDefinition,
)
from app.schemas.player_build import PlayerElfBuildCreate, PlayerElfBuildOut
from app.utils.json import dumps_json


class PlayerElfBuildService:
    """
    己方配置业务服务。

    这里集中处理配置创建时的校验、面板属性计算和技能槽保存，避免 API 层直接
    操作多张表。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_build(self, payload: PlayerElfBuildCreate) -> PlayerElfBuildOut:
        """
        创建己方精灵配置。

        创建时会：
        1. 校验精灵、性格和技能是否存在；
        2. 根据当前规则计算面板属性；
        3. 保存配置主体与技能槽；
        4. 如果 is_default=True，清除同精灵其他默认配置标记。
        """
        elf = self.db.get(ElfDefinition, payload.elf_id)
        if elf is None or elf.deleted_at is not None:
            raise ValueError(f"精灵不存在：{payload.elf_id}")

        nature = self.db.get(NatureDefinition, payload.nature_id)
        if nature is None or nature.deleted_at is not None:
            raise ValueError(f"性格不存在：{payload.nature_id}")

        self._validate_skill_ids(payload.skill_ids)

        individual = IndividualTalentDistribution(
            **payload.individual_talent_distribution.model_dump()
        )
        final_stats = StatCalculator.calculate_panel_stats(
            base=self._elf_to_base_talent_block(elf),
            individual=individual,
            nature=self._nature_to_rule(nature),
        )

        if payload.is_default:
            self._clear_default_builds(payload.elf_id)

        build = PlayerElfBuild(
            build_id=f"build_{uuid4().hex}",
            build_name=payload.build_name,
            elf_id=payload.elf_id,
            nature_id=payload.nature_id,
            individual_talent_distribution_json=dumps_json(individual),
            final_stats_json=dumps_json(final_stats),
            is_default=payload.is_default,
            notes=payload.notes,
        )
        self.db.add(build)
        self.db.flush()

        for slot_index, skill_id in enumerate(payload.skill_ids):
            self.db.add(
                PlayerElfBuildSkill(
                    build_id=build.build_id,
                    slot_index=slot_index,
                    skill_id=skill_id,
                )
            )

        self.db.commit()
        return self.get_build(build.build_id)

    def get_build(self, build_id: str) -> PlayerElfBuildOut:
        """获取单个己方配置，并合并技能槽列表。"""
        build = self.db.get(PlayerElfBuild, build_id)
        if build is None or build.deleted_at is not None:
            raise LookupError(f"己方配置不存在：{build_id}")
        return self._to_out(build)

    def list_builds(self, elf_id: str | None = None) -> list[PlayerElfBuildOut]:
        """按精灵过滤或列出全部未删除配置。"""
        stmt = select(PlayerElfBuild).where(PlayerElfBuild.deleted_at.is_(None))
        if elf_id is not None:
            stmt = stmt.where(PlayerElfBuild.elf_id == elf_id)
        stmt = stmt.order_by(PlayerElfBuild.elf_id, PlayerElfBuild.build_name)
        return [self._to_out(item) for item in self.db.scalars(stmt).all()]

    def _validate_skill_ids(self, skill_ids: list[str]) -> None:
        """校验技能 ID 是否都存在。"""
        if not skill_ids:
            return
        existing_ids = set(
            self.db.scalars(
                select(SkillDefinition.skill_id).where(SkillDefinition.skill_id.in_(skill_ids))
            ).all()
        )
        missing_ids = [skill_id for skill_id in skill_ids if skill_id not in existing_ids]
        if missing_ids:
            raise ValueError(f"技能不存在：{', '.join(missing_ids)}")

    def _clear_default_builds(self, elf_id: str) -> None:
        """同一精灵只保留一个默认配置。"""
        builds = self.db.scalars(
            select(PlayerElfBuild).where(
                PlayerElfBuild.elf_id == elf_id,
                PlayerElfBuild.deleted_at.is_(None),
                PlayerElfBuild.is_default.is_(True),
            )
        ).all()
        for item in builds:
            item.is_default = False

    def _to_out(self, build: PlayerElfBuild) -> PlayerElfBuildOut:
        """将配置主体与技能槽合并为 API 输出结构。"""
        skill_rows = self.db.scalars(
            select(PlayerElfBuildSkill)
            .where(PlayerElfBuildSkill.build_id == build.build_id)
            .order_by(PlayerElfBuildSkill.slot_index)
        ).all()
        return PlayerElfBuildOut(
            build_id=build.build_id,
            build_name=build.build_name,
            elf_id=build.elf_id,
            nature_id=build.nature_id,
            individual_talent_distribution_json=build.individual_talent_distribution_json,
            final_stats_json=build.final_stats_json,
            skill_ids=[row.skill_id for row in skill_rows],
            is_default=build.is_default,
            notes=build.notes,
        )

    @staticmethod
    def _elf_to_base_talent_block(elf: ElfDefinition) -> BaseTalentBlock:
        """从精灵静态定义提取六维种族资质。"""
        return BaseTalentBlock(
            hp=elf.base_hp_talent,
            physical_attack=elf.base_physical_attack_talent,
            physical_defense=elf.base_physical_defense_talent,
            magic_attack=elf.base_magic_attack_talent,
            magic_defense=elf.base_magic_defense_talent,
            speed=elf.base_speed_talent,
        )

    @staticmethod
    def _nature_to_rule(nature: NatureDefinition) -> NatureRule:
        """将数据库性格定义转换为计算器使用的 NatureRule。"""
        return NatureRule(
            nature_id=nature.nature_id,
            positive_stat=StatKey(nature.positive_stat),
            negative_stat=StatKey(nature.negative_stat),
        )

    def replace_build_skills(self, build_id: str, skill_ids: list[str]) -> PlayerElfBuildOut:
        """
        替换某个配置的技能槽。

        第一阶段主要用于手动纠错。后续可增加技能是否属于该精灵可学习技能池的
        严格校验。
        """
        build = self.db.get(PlayerElfBuild, build_id)
        if build is None or build.deleted_at is not None:
            raise LookupError(f"己方配置不存在：{build_id}")
        self._validate_skill_ids(skill_ids)
        self.db.execute(delete(PlayerElfBuildSkill).where(PlayerElfBuildSkill.build_id == build_id))
        for slot_index, skill_id in enumerate(skill_ids):
            self.db.add(
                PlayerElfBuildSkill(
                    build_id=build_id,
                    slot_index=slot_index,
                    skill_id=skill_id,
                )
            )
        self.db.commit()
        return self.get_build(build_id)
