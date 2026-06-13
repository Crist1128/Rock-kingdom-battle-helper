"""drop legacy candidate tables

Revision ID: 0006_drop_legacy_candidate_tables
Revises: 0005_relax_estimate_evidence_source
Create Date: 2026-06-09 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_drop_legacy_candidate_tables"
down_revision: str | None = "0005_relax_estimate_evidence_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    """删除已经废弃的候选空间表和旧计算缓存表。"""
    op.drop_index("idx_calculation_cache_key", table_name="calculation_cache")
    op.drop_table("calculation_cache")
    op.drop_index("idx_build_candidate_confidence", table_name="build_candidate")
    op.drop_index("idx_build_candidate_battle_elf_excluded", table_name="build_candidate")
    op.drop_table("build_candidate")


def downgrade() -> None:
    """回滚时按 0001 初始结构重建旧候选表和计算缓存表。"""
    op.create_table(
        "build_candidate",
        sa.Column("candidate_id", sa.String(), primary_key=True),
        sa.Column("battle_id", sa.String(), sa.ForeignKey("battle.battle_id"), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("elf_id", sa.String(), sa.ForeignKey("elf_definition.elf_id"), nullable=False),
        sa.Column("nature_id", sa.String(), sa.ForeignKey("nature_definition.nature_id"), nullable=False),
        sa.Column("individual_talent_distribution_json", sa.Text(), nullable=False),
        sa.Column("final_hp", sa.Integer(), nullable=False),
        sa.Column("final_physical_attack", sa.Integer(), nullable=False),
        sa.Column("final_physical_defense", sa.Integer(), nullable=False),
        sa.Column("final_magic_attack", sa.Integer(), nullable=False),
        sa.Column("final_magic_defense", sa.Integer(), nullable=False),
        sa.Column("final_speed", sa.Integer(), nullable=False),
        sa.Column("possible_skill_ids_json", sa.Text(), nullable=True),
        sa.Column("confirmed_skill_ids_json", sa.Text(), nullable=True),
        sa.Column("skill_weights_json", sa.Text(), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("is_excluded", sa.Boolean(), nullable=False),
        sa.Column("excluded_reason", sa.Text(), nullable=True),
        sa.Column("evidence_ids_json", sa.Text(), nullable=True),
        sa.Column("matched_event_ids_json", sa.Text(), nullable=True),
        sa.Column("mismatched_event_ids_json", sa.Text(), nullable=True),
        *_timestamp_columns(),
    )
    op.create_index(
        "idx_build_candidate_battle_elf_excluded",
        "build_candidate",
        ["battle_id", "elf_id", "is_excluded"],
    )
    op.create_index(
        "idx_build_candidate_confidence",
        "build_candidate",
        ["battle_id", "elf_id", "confidence"],
    )

    op.create_table(
        "calculation_cache",
        sa.Column("cache_id", sa.String(), primary_key=True),
        sa.Column("cache_key", sa.String(), nullable=False),
        sa.Column("cache_type", sa.String(), nullable=False),
        sa.Column("battle_id", sa.String(), nullable=True),
        sa.Column("snapshot_id", sa.String(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("expire_at", sa.String(), nullable=True),
        *_timestamp_columns(),
    )
    op.create_index("idx_calculation_cache_key", "calculation_cache", ["cache_key"], unique=True)
