"""add team presets for preparation lineup shortcuts

Revision ID: 0003_team_presets
Revises: 0002_event_correction_resource_mvp
Create Date: 2026-06-07 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_team_presets"
down_revision: str | None = "0002_event_correction_resource_mvp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增配队预设主表和槽位表。"""
    op.create_table(
        "team_preset",
        sa.Column("preset_id", sa.String(), nullable=False),
        sa.Column("preset_name", sa.String(), nullable=False),
        sa.Column("side_usage", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("preset_id", name=op.f("pk_team_preset")),
    )
    op.create_index("idx_team_preset_name", "team_preset", ["preset_name"])
    op.create_index(
        "idx_team_preset_usage_source",
        "team_preset",
        ["side_usage", "source_type"],
    )

    op.create_table(
        "team_preset_slot",
        sa.Column("slot_id", sa.String(), nullable=False),
        sa.Column("preset_id", sa.String(), nullable=False),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.Column("elf_id", sa.String(), nullable=False),
        sa.Column("build_id", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["build_id"],
            ["player_elf_build.build_id"],
            name=op.f("fk_team_preset_slot_build_id_player_elf_build"),
        ),
        sa.ForeignKeyConstraint(
            ["elf_id"],
            ["elf_definition.elf_id"],
            name=op.f("fk_team_preset_slot_elf_id_elf_definition"),
        ),
        sa.ForeignKeyConstraint(
            ["preset_id"],
            ["team_preset.preset_id"],
            name=op.f("fk_team_preset_slot_preset_id_team_preset"),
        ),
        sa.PrimaryKeyConstraint("slot_id", name=op.f("pk_team_preset_slot")),
        sa.UniqueConstraint(
            "preset_id",
            "slot_index",
            name="uq_team_preset_slot_preset_slot",
        ),
    )
    op.create_index("idx_team_preset_slot_elf", "team_preset_slot", ["elf_id"])
    op.create_index("idx_team_preset_slot_preset", "team_preset_slot", ["preset_id"])


def downgrade() -> None:
    """回滚配队预设表。"""
    op.drop_index("idx_team_preset_slot_preset", table_name="team_preset_slot")
    op.drop_index("idx_team_preset_slot_elf", table_name="team_preset_slot")
    op.drop_table("team_preset_slot")
    op.drop_index("idx_team_preset_usage_source", table_name="team_preset")
    op.drop_index("idx_team_preset_name", table_name="team_preset")
    op.drop_table("team_preset")
