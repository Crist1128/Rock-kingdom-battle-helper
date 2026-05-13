from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BattleEvent(TimestampMixin, Base):
    """通用战斗事件。业务事实都先记录为 BattleEvent。"""

    __tablename__ = "battle_event"
    __table_args__ = (
        Index("idx_battle_event_battle_turn", "battle_id", "turn_number", "created_at"),
        Index("idx_battle_event_type", "battle_id", "event_type"),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)

    actor_side: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_side: Mapped[str | None] = mapped_column(String, nullable=True)
    target_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)

    skill_id: Mapped[str | None] = mapped_column(String, nullable=True)
    skill_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)

    source: Mapped[str] = mapped_column(String, nullable=False, default="manual_input")
    recognition_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class DamageEvent(TimestampMixin, Base):
    """伤害事件详情。区分单次、动画多段最终总伤害、连击。"""

    __tablename__ = "damage_event"
    __table_args__ = (
        Index("idx_damage_event_battle_event", "battle_event_id", unique=True),
        Index("idx_damage_event_battle_pair", "battle_id", "attacker_elf_id", "defender_elf_id"),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    battle_event_id: Mapped[str] = mapped_column(ForeignKey("battle_event.event_id"), nullable=False)

    attacker_side: Mapped[str | None] = mapped_column(String, nullable=True)
    attacker_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    defender_side: Mapped[str | None] = mapped_column(String, nullable=True)
    defender_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    skill_id: Mapped[str | None] = mapped_column(String, nullable=True)

    damage_display_type: Mapped[str] = mapped_column(String, nullable=False)
    damage_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_total_damage_value: Mapped[int | None] = mapped_column(Integer, nullable=True)

    per_hit_damage_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_total_damage_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    combo_count_source: Mapped[str | None] = mapped_column(String, nullable=True)
    combo_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    hp_percent_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    hp_percent_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    hp_percent_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    enemy_hp_percent_damage: Mapped[float | None] = mapped_column(Float, nullable=True)

    type_effectiveness: Mapped[float | None] = mapped_column(Float, nullable=True)
    formula_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    special_formula_id: Mapped[str | None] = mapped_column(String, nullable=True)

    calculation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    recognition_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class EffectChangeEvent(TimestampMixin, Base):
    """状态变化事件详情。"""

    __tablename__ = "effect_change_event"
    __table_args__ = (
        Index("idx_effect_change_battle_event", "battle_event_id"),
        Index("idx_effect_change_target", "battle_id", "target_side", "target_elf_id"),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    battle_event_id: Mapped[str] = mapped_column(ForeignKey("battle_event.event_id"), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)

    change_type: Mapped[str] = mapped_column(String, nullable=False)
    effect_instance_id: Mapped[str | None] = mapped_column(String, nullable=True)
    effect_id: Mapped[str] = mapped_column(String, nullable=False)
    effect_name: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)

    target_side: Mapped[str | None] = mapped_column(String, nullable=True)
    target_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_skill_slot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_scope: Mapped[str] = mapped_column(String, nullable=False)

    layers_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    layers_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_after: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_skill_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    condition_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(String, nullable=False, default="manual_input")
    recognition_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ResourceChangeEvent(TimestampMixin, Base):
    """生命 / 能量变化事件详情。"""

    __tablename__ = "resource_change_event"
    __table_args__ = (Index("idx_resource_change_battle_event", "battle_event_id"),)

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    battle_event_id: Mapped[str] = mapped_column(ForeignKey("battle_event.event_id"), nullable=False)

    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    change_type: Mapped[str] = mapped_column(String, nullable=False)

    source_side: Mapped[str | None] = mapped_column(String, nullable=True)
    source_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_side: Mapped[str | None] = mapped_column(String, nullable=True)
    target_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)

    value_type: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    before_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    after_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
