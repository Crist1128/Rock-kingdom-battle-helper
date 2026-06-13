"""add battle runtime form fields

Revision ID: 0007_battle_runtime_form
Revises: 0006_drop_legacy_candidate_tables
Create Date: 2026-06-12 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_battle_runtime_form"
down_revision: str | None = "0006_drop_legacy_candidate_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为战斗精灵状态增加运行时有效形态与培养快照字段。"""
    op.add_column(
        "battle_elf_state",
        sa.Column("runtime_form_elf_id", sa.String(), nullable=True),
    )
    op.add_column(
        "battle_elf_state",
        sa.Column("runtime_form_elf_name", sa.String(), nullable=True),
    )
    op.add_column(
        "battle_elf_state",
        sa.Column("runtime_form_avatar", sa.String(), nullable=True),
    )
    op.add_column(
        "battle_elf_state",
        sa.Column("runtime_form_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "battle_elf_state",
        sa.Column("nature_id", sa.String(), nullable=True),
    )
    op.add_column(
        "battle_elf_state",
        sa.Column("individual_talent_distribution_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """回滚运行时有效形态与培养快照字段。"""
    op.drop_column("battle_elf_state", "individual_talent_distribution_json")
    op.drop_column("battle_elf_state", "nature_id")
    op.drop_column("battle_elf_state", "runtime_form_reason")
    op.drop_column("battle_elf_state", "runtime_form_avatar")
    op.drop_column("battle_elf_state", "runtime_form_elf_name")
    op.drop_column("battle_elf_state", "runtime_form_elf_id")
