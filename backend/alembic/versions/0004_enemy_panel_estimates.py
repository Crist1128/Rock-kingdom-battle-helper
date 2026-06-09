"""add enemy panel estimate tables

Revision ID: 0004_enemy_panel_estimates
Revises: 0003_team_presets
Create Date: 2026-06-08 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_enemy_panel_estimates"
down_revision: str | None = "0003_team_presets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增敌方面板估计档案与事件级证据表。"""
    op.create_table(
        "enemy_panel_estimate",
        sa.Column("estimate_id", sa.String(), nullable=False),
        sa.Column("battle_id", sa.String(), nullable=False),
        sa.Column("battle_elf_state_id", sa.String(), nullable=False),
        sa.Column("elf_id", sa.String(), nullable=False),
        sa.Column("default_config_json", sa.Text(), nullable=True),
        sa.Column("default_panel_json", sa.Text(), nullable=True),
        sa.Column("estimated_panel_json", sa.Text(), nullable=True),
        sa.Column("stat_constraints_json", sa.Text(), nullable=True),
        sa.Column("confidence_json", sa.Text(), nullable=True),
        sa.Column("unknown_factors_json", sa.Text(), nullable=True),
        sa.Column("confirmed_skill_ids_json", sa.Text(), nullable=True),
        sa.Column("evidence_summary_json", sa.Text(), nullable=True),
        sa.Column("updated_by_event_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["battle_elf_state_id"],
            ["battle_elf_state.state_id"],
            name=op.f("fk_enemy_panel_estimate_battle_elf_state_id_battle_elf_state"),
        ),
        sa.ForeignKeyConstraint(
            ["battle_id"],
            ["battle.battle_id"],
            name=op.f("fk_enemy_panel_estimate_battle_id_battle"),
        ),
        sa.ForeignKeyConstraint(
            ["elf_id"],
            ["elf_definition.elf_id"],
            name=op.f("fk_enemy_panel_estimate_elf_id_elf_definition"),
        ),
        sa.PrimaryKeyConstraint("estimate_id", name=op.f("pk_enemy_panel_estimate")),
    )
    op.create_index(
        "idx_enemy_panel_estimate_battle_elf",
        "enemy_panel_estimate",
        ["battle_id", "elf_id"],
    )
    op.create_index(
        "idx_enemy_panel_estimate_state",
        "enemy_panel_estimate",
        ["battle_elf_state_id"],
    )

    op.create_table(
        "enemy_panel_estimate_evidence",
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("estimate_id", sa.String(), nullable=False),
        sa.Column("battle_id", sa.String(), nullable=False),
        sa.Column("source_event_id", sa.String(), nullable=False),
        sa.Column("observation_type", sa.String(), nullable=False),
        sa.Column("inferred_stats_json", sa.Text(), nullable=True),
        sa.Column("constraint_delta_json", sa.Text(), nullable=True),
        sa.Column("formula_context_json", sa.Text(), nullable=True),
        sa.Column("unknown_factors_json", sa.Text(), nullable=True),
        sa.Column("conflict_json", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["battle_id"],
            ["battle.battle_id"],
            name=op.f("fk_enemy_panel_estimate_evidence_battle_id_battle"),
        ),
        sa.ForeignKeyConstraint(
            ["estimate_id"],
            ["enemy_panel_estimate.estimate_id"],
            name=op.f("fk_enemy_panel_estimate_evidence_estimate_id_enemy_panel_estimate"),
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"],
            ["battle_event.event_id"],
            name=op.f("fk_enemy_panel_estimate_evidence_source_event_id_battle_event"),
        ),
        sa.PrimaryKeyConstraint("evidence_id", name=op.f("pk_enemy_panel_estimate_evidence")),
    )
    op.create_index(
        "idx_enemy_panel_estimate_evidence_estimate",
        "enemy_panel_estimate_evidence",
        ["estimate_id", "created_at"],
    )
    op.create_index(
        "idx_enemy_panel_estimate_evidence_event",
        "enemy_panel_estimate_evidence",
        ["source_event_id"],
    )


def downgrade() -> None:
    """回滚敌方面板估计表。"""
    op.drop_index(
        "idx_enemy_panel_estimate_evidence_event",
        table_name="enemy_panel_estimate_evidence",
    )
    op.drop_index(
        "idx_enemy_panel_estimate_evidence_estimate",
        table_name="enemy_panel_estimate_evidence",
    )
    op.drop_table("enemy_panel_estimate_evidence")
    op.drop_index("idx_enemy_panel_estimate_state", table_name="enemy_panel_estimate")
    op.drop_index("idx_enemy_panel_estimate_battle_elf", table_name="enemy_panel_estimate")
    op.drop_table("enemy_panel_estimate")
