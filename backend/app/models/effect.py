from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BattleEffectInstance(TimestampMixin, Base):
    """战斗内状态实例。印记、天气、异常、普通增减益都落在此表。"""

    __tablename__ = "battle_effect_instance"
    __table_args__ = (
        Index("idx_effect_instance_battle_owner", "battle_id", "owner_side", "owner_elf_id"),
        Index("idx_effect_instance_battle_category", "battle_id", "category"),
        Index("idx_effect_instance_active", "battle_id", "is_active"),
    )

    instance_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    effect_id: Mapped[str] = mapped_column(ForeignKey("effect_definition.effect_id"), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)

    owner_scope: Mapped[str] = mapped_column(String, nullable=False)
    owner_side: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_skill_slot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    field_id: Mapped[str | None] = mapped_column(String, nullable=True)

    source_side: Mapped[str | None] = mapped_column(String, nullable=True)
    source_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_skill_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String, nullable=True)

    layers: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    remaining_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    applied_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expire_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_updated_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)

    recognition_source: Mapped[str | None] = mapped_column(String, nullable=True)
    recognition_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class BattleEffectSnapshot(TimestampMixin, Base):
    """状态快照。伤害、治疗、能量变化、切换事件都应引用快照。"""

    __tablename__ = "battle_effect_snapshot"
    __table_args__ = (
        Index("idx_effect_snapshot_battle_turn", "battle_id", "turn_number", "created_at"),
        Index("idx_effect_snapshot_source_event", "source_event_id"),
    )

    snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)

    active_effect_instance_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    self_active_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    enemy_active_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)

    self_elf_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    enemy_elf_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    self_side_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    enemy_side_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_slot_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    turn_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    full_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
