from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BuildCandidate(TimestampMixin, Base):
    """敌方候选配置。只保存面板属性，不保存状态修正后的临时属性。"""

    __tablename__ = "build_candidate"
    __table_args__ = (
        Index("idx_build_candidate_battle_elf_excluded", "battle_id", "elf_id", "is_excluded"),
        Index("idx_build_candidate_confidence", "battle_id", "elf_id", "confidence"),
    )

    candidate_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False, default="enemy")
    elf_id: Mapped[str] = mapped_column(ForeignKey("elf_definition.elf_id"), nullable=False)
    nature_id: Mapped[str] = mapped_column(ForeignKey("nature_definition.nature_id"), nullable=False)
    individual_talent_distribution_json: Mapped[str] = mapped_column(Text, nullable=False)

    final_hp: Mapped[int] = mapped_column(Integer, nullable=False)
    final_physical_attack: Mapped[int] = mapped_column(Integer, nullable=False)
    final_physical_defense: Mapped[int] = mapped_column(Integer, nullable=False)
    final_magic_attack: Mapped[int] = mapped_column(Integer, nullable=False)
    final_magic_defense: Mapped[int] = mapped_column(Integer, nullable=False)
    final_speed: Mapped[int] = mapped_column(Integer, nullable=False)

    possible_skill_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_skill_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_weights_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excluded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_event_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    mismatched_event_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class CalculationCache(TimestampMixin, Base):
    """计算缓存，可选表。用于缓存伤害、速度等昂贵计算。"""

    __tablename__ = "calculation_cache"
    __table_args__ = (Index("idx_calculation_cache_key", "cache_key", unique=True),)

    cache_id: Mapped[str] = mapped_column(String, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String, nullable=False)
    cache_type: Mapped[str] = mapped_column(String, nullable=False)
    battle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    expire_at: Mapped[str | None] = mapped_column(String, nullable=True)
