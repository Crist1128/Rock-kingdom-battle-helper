"""精灵进化链查询服务。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.static import ElfDefinition, ElfEvolutionChain, ElfEvolutionStage
from app.schemas.static import (
    ElfEvolutionChainGroupOut,
    ElfEvolutionChainOut,
    ElfEvolutionStageOut,
)


class EvolutionChainService:
    """提供独立进化链表到 API 输出的转换。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_chain_for_elf(self, elf_id: str) -> ElfEvolutionChainOut | None:
        """查询某只精灵所在进化链，并返回可用于运行时形态切换的阶段列表。"""
        elf = self.db.get(ElfDefinition, elf_id)
        if elf is None or elf.deleted_at is not None:
            return None

        chain_ids = list(
            self.db.scalars(
                select(ElfEvolutionStage.chain_id)
                .join(ElfEvolutionChain, ElfEvolutionChain.chain_id == ElfEvolutionStage.chain_id)
                .where(
                    ElfEvolutionStage.elf_id == elf_id,
                    ElfEvolutionChain.deleted_at.is_(None),
                )
                .distinct()
            )
        )
        if not chain_ids:
            return ElfEvolutionChainOut(current_elf_id=elf_id, chains=[], stages=[])

        chain_rows = list(
            self.db.scalars(
                select(ElfEvolutionChain)
                .where(
                    ElfEvolutionChain.chain_id.in_(chain_ids),
                    ElfEvolutionChain.deleted_at.is_(None),
                )
                .order_by(ElfEvolutionChain.chain_id)
            )
        )
        stage_rows = self.db.execute(
            select(ElfEvolutionStage, ElfDefinition)
            .join(ElfDefinition, ElfDefinition.elf_id == ElfEvolutionStage.elf_id)
            .where(
                ElfEvolutionStage.chain_id.in_(chain_ids),
                ElfDefinition.deleted_at.is_(None),
            )
            .order_by(
                ElfEvolutionStage.chain_id,
                ElfEvolutionStage.stage_index,
                ElfDefinition.elf_name,
                ElfEvolutionStage.elf_id,
            )
        ).all()

        stages_by_chain: dict[str, list[ElfEvolutionStageOut]] = {}
        flattened: list[ElfEvolutionStageOut] = []
        seen_elf_ids: set[str] = set()
        for stage, definition in stage_rows:
            item = self._stage_to_out(stage, definition)
            stages_by_chain.setdefault(stage.chain_id, []).append(item)
            if item.elf_id not in seen_elf_ids:
                flattened.append(item)
                seen_elf_ids.add(item.elf_id)

        chains = [
            ElfEvolutionChainGroupOut(
                chain_id=chain.chain_id,
                chain_name=chain.chain_name,
                source=chain.source,
                data_version=chain.data_version,
                stages=stages_by_chain.get(chain.chain_id, []),
            )
            for chain in chain_rows
        ]
        return ElfEvolutionChainOut(current_elf_id=elf_id, chains=chains, stages=flattened)

    @staticmethod
    def _stage_to_out(stage: ElfEvolutionStage, definition: ElfDefinition) -> ElfEvolutionStageOut:
        return ElfEvolutionStageOut(
            chain_id=stage.chain_id,
            elf_id=definition.elf_id,
            elf_name=definition.elf_name,
            avatar=definition.avatar,
            element_types_json=definition.element_types_json,
            stage_index=stage.stage_index,
            stage_name=stage.stage_name,
            form_name=stage.form_name,
            evolves_from_elf_id=stage.evolves_from_elf_id,
            condition_json=stage.condition_json,
            base_hp_talent=definition.base_hp_talent,
            base_physical_attack_talent=definition.base_physical_attack_talent,
            base_physical_defense_talent=definition.base_physical_defense_talent,
            base_magic_attack_talent=definition.base_magic_attack_talent,
            base_magic_defense_talent=definition.base_magic_defense_talent,
            base_speed_talent=definition.base_speed_talent,
        )
