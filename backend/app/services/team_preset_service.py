"""
配队预设服务。

负责保存和读取准备阶段可复用的阵容模板。己方配队必须引用已计算面板的
PlayerElfBuild；敌方热门阵容允许只引用精灵定义。
"""

from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.base import utc_now
from app.models.static import ElfDefinition, PlayerElfBuild, TeamPreset, TeamPresetSlot
from app.schemas.team_preset import (
    TeamPresetCreate,
    TeamPresetOut,
    TeamPresetSlotInput,
    TeamPresetSlotOut,
    TeamPresetUpdate,
)


class TeamPresetService:
    """配队预设业务服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_preset(self, payload: TeamPresetCreate) -> TeamPresetOut:
        """创建配队预设并写入槽位。"""
        self._validate_payload(payload)
        preset = TeamPreset(
            preset_id=f"team_preset_{uuid4().hex}",
            preset_name=payload.preset_name,
            side_usage=payload.side_usage,
            source_type=payload.source_type,
            notes=payload.notes,
        )
        self.db.add(preset)
        self.db.flush()
        self._replace_slots(preset.preset_id, payload.slots)
        self.db.commit()
        return self.get_preset(preset.preset_id)

    def update_preset(self, preset_id: str, payload: TeamPresetUpdate) -> TeamPresetOut:
        """整单更新配队预设和槽位。"""
        preset = self._require_preset(preset_id)
        self._validate_payload(payload)
        preset.preset_name = payload.preset_name
        preset.side_usage = payload.side_usage
        preset.source_type = payload.source_type
        preset.notes = payload.notes
        self._replace_slots(preset_id, payload.slots)
        self.db.commit()
        return self.get_preset(preset_id)

    def delete_preset(self, preset_id: str) -> None:
        """软删除配队预设。"""
        preset = self._require_preset(preset_id)
        preset.deleted_at = utc_now()
        self.db.commit()

    def get_preset(self, preset_id: str) -> TeamPresetOut:
        """读取单个配队预设。"""
        return self._to_out(self._require_preset(preset_id))

    def list_presets(
        self,
        *,
        side_usage: str | None = None,
        source_type: str | None = None,
    ) -> list[TeamPresetOut]:
        """列出配队预设，可按使用侧和来源筛选。"""
        stmt = select(TeamPreset).where(TeamPreset.deleted_at.is_(None))
        if side_usage is not None:
            if side_usage not in {"self", "enemy", "both"}:
                raise ValueError("side_usage 只能是 self、enemy 或 both")
            stmt = stmt.where(TeamPreset.side_usage.in_([side_usage, "both"]))
        if source_type is not None:
            if source_type not in {"custom", "popular"}:
                raise ValueError("source_type 只能是 custom 或 popular")
            stmt = stmt.where(TeamPreset.source_type == source_type)
        stmt = stmt.order_by(TeamPreset.source_type.desc(), TeamPreset.updated_at.desc())
        return [self._to_out(item) for item in self.db.scalars(stmt).all()]

    def _replace_slots(self, preset_id: str, slots: list[TeamPresetSlotInput]) -> None:
        """重建配队槽位。"""
        self.db.execute(delete(TeamPresetSlot).where(TeamPresetSlot.preset_id == preset_id))
        for slot in slots:
            self.db.add(
                TeamPresetSlot(
                    slot_id=f"team_preset_slot_{uuid4().hex}",
                    preset_id=preset_id,
                    slot_index=slot.slot_index,
                    elf_id=slot.elf_id,
                    build_id=slot.build_id,
                    notes=slot.notes,
                )
            )

    def _validate_payload(self, payload: TeamPresetCreate | TeamPresetUpdate) -> None:
        """校验槽位中的精灵和配置引用。"""
        if payload.side_usage == "self" and any(slot.build_id is None for slot in payload.slots):
            raise ValueError("己方配队槽位必须选择 build_id")

        elf_ids = {slot.elf_id for slot in payload.slots}
        if elf_ids:
            existing_elf_ids = set(
                self.db.scalars(
                    select(ElfDefinition.elf_id).where(ElfDefinition.elf_id.in_(elf_ids))
                ).all()
            )
            missing_elf_ids = sorted(elf_ids - existing_elf_ids)
            if missing_elf_ids:
                raise ValueError(f"精灵不存在：{', '.join(missing_elf_ids)}")

        build_ids = {slot.build_id for slot in payload.slots if slot.build_id}
        if not build_ids:
            return
        builds = {
            build.build_id: build
            for build in self.db.scalars(
                select(PlayerElfBuild).where(
                    PlayerElfBuild.build_id.in_(build_ids),
                    PlayerElfBuild.deleted_at.is_(None),
                )
            ).all()
        }
        missing_build_ids = sorted(build_id for build_id in build_ids if build_id not in builds)
        if missing_build_ids:
            raise ValueError(f"己方配置不存在：{', '.join(missing_build_ids)}")

        for slot in payload.slots:
            if not slot.build_id:
                continue
            build = builds[slot.build_id]
            if build.elf_id != slot.elf_id:
                raise ValueError(f"槽位 {slot.slot_index + 1} 的 build_id 与 elf_id 不一致")

    def _require_preset(self, preset_id: str) -> TeamPreset:
        """读取未删除配队预设。"""
        preset = self.db.get(TeamPreset, preset_id)
        if preset is None or preset.deleted_at is not None:
            raise LookupError(f"配队预设不存在：{preset_id}")
        return preset

    def _to_out(self, preset: TeamPreset) -> TeamPresetOut:
        """合并槽位、精灵展示字段和配置名。"""
        slots = self.db.scalars(
            select(TeamPresetSlot)
            .where(TeamPresetSlot.preset_id == preset.preset_id)
            .order_by(TeamPresetSlot.slot_index)
        ).all()
        return TeamPresetOut(
            preset_id=preset.preset_id,
            preset_name=preset.preset_name,
            side_usage=preset.side_usage,
            source_type=preset.source_type,
            notes=preset.notes,
            slots=[self._slot_to_out(slot) for slot in slots],
            created_at=preset.created_at,
            updated_at=preset.updated_at,
        )

    def _slot_to_out(self, slot: TeamPresetSlot) -> TeamPresetSlotOut:
        """转换单个槽位输出。"""
        elf = self.db.get(ElfDefinition, slot.elf_id)
        build = self.db.get(PlayerElfBuild, slot.build_id) if slot.build_id else None
        return TeamPresetSlotOut(
            slot_id=slot.slot_id,
            preset_id=slot.preset_id,
            slot_index=slot.slot_index,
            elf_id=slot.elf_id,
            elf_name=elf.elf_name if elf is not None else None,
            avatar=elf.avatar if elf is not None else None,
            element_types_json=elf.element_types_json if elf is not None else None,
            build_id=slot.build_id,
            build_name=build.build_name if build is not None else None,
            notes=slot.notes,
        )
