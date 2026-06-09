"""敌方面板实时估计模型。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, utc_now


class EnemyPanelEstimate(TimestampMixin, Base):
    """敌方精灵的当前面板估计档案。"""

    __tablename__ = "enemy_panel_estimate"
    __table_args__ = (
        Index("idx_enemy_panel_estimate_battle_elf", "battle_id", "elf_id"),
        Index("idx_enemy_panel_estimate_state", "battle_elf_state_id"),
    )

    estimate_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    battle_elf_state_id: Mapped[str] = mapped_column(
        ForeignKey("battle_elf_state.state_id"),
        nullable=False,
    )
    elf_id: Mapped[str] = mapped_column(ForeignKey("elf_definition.elf_id"), nullable=False)

    default_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_panel_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_panel_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    stat_constraints_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unknown_factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_skill_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_event_id: Mapped[str | None] = mapped_column(String, nullable=True)


class EnemyPanelEstimateEvidence(Base):
    """敌方面板估计的事件级证据。"""

    __tablename__ = "enemy_panel_estimate_evidence"
    __table_args__ = (
        Index("idx_enemy_panel_estimate_evidence_estimate", "estimate_id", "created_at"),
        Index("idx_enemy_panel_estimate_evidence_event", "source_event_id"),
    )

    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    estimate_id: Mapped[str] = mapped_column(
        ForeignKey("enemy_panel_estimate.estimate_id"),
        nullable=False,
    )
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String, nullable=False)
    observation_type: Mapped[str] = mapped_column(String, nullable=False)
    inferred_stats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraint_delta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    formula_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unknown_factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflict_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
