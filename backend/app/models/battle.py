from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Battle(TimestampMixin, Base):
    """战斗主表。"""

    __tablename__ = "battle"
    __table_args__ = (Index("idx_battle_phase", "phase"),)

    battle_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_name: Mapped[str | None] = mapped_column(String, nullable=True)
    phase: Mapped[str] = mapped_column(String, nullable=False, default="preparation")
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    self_active_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    enemy_active_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class BattleElfState(TimestampMixin, Base):
    """战斗中每只精灵运行时状态。所有状态通过 BattleEffectInstance 关联。"""

    __tablename__ = "battle_elf_state"
    __table_args__ = (
        Index("idx_battle_elf_state_battle_side_elf", "battle_id", "side", "elf_id"),
        Index("idx_battle_elf_state_active", "battle_id", "side", "is_active_elf"),
    )

    state_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    elf_id: Mapped[str] = mapped_column(ForeignKey("elf_definition.elf_id"), nullable=False)
    elf_name: Mapped[str] = mapped_column(String, nullable=False)
    avatar: Mapped[str] = mapped_column(String, nullable=False)

    panel_stats_json: Mapped[str] = mapped_column(Text, nullable=False)
    current_hp_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_hp_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)

    skill_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_skill_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_effect_instance_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active_elf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_defeated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_switch_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BattleSkillSlot(TimestampMixin, Base):
    """战斗中的技能槽状态，用于能耗、威力、冷却、位置等技能槽修正。"""

    __tablename__ = "battle_skill_slot"
    __table_args__ = (
        Index("idx_battle_skill_slot_battle_elf", "battle_id", "side", "elf_id"),
        Index("idx_battle_skill_slot_skill", "skill_id"),
    )

    slot_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    elf_id: Mapped[str] = mapped_column(ForeignKey("elf_definition.elf_id"), nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_definition.skill_id"), nullable=False)
    current_energy_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cooldown_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_effect_instance_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
