"""Add elf evolution chain tables.

Revision ID: 0009_elf_evolution_chains
Revises: 0008_skill_raw_description
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0009_elf_evolution_chains"
down_revision: str | None = "0008_skill_raw_description"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create low-coupling evolution chain tables."""
    op.create_table(
        "elf_evolution_chain",
        sa.Column("chain_id", sa.String(), nullable=False),
        sa.Column("chain_key", sa.String(), nullable=False),
        sa.Column("chain_name", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("data_version", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("chain_id", name=op.f("pk_elf_evolution_chain")),
        sa.UniqueConstraint("chain_key", name="uq_elf_evolution_chain_chain_key"),
    )
    op.create_index(
        "idx_elf_evolution_chain_source",
        "elf_evolution_chain",
        ["source"],
        unique=False,
    )
    op.create_table(
        "elf_evolution_stage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chain_id", sa.String(), nullable=False),
        sa.Column("elf_id", sa.String(), nullable=False),
        sa.Column("stage_index", sa.Integer(), nullable=False),
        sa.Column("stage_name", sa.String(), nullable=False),
        sa.Column("form_name", sa.String(), nullable=True),
        sa.Column("evolves_from_elf_id", sa.String(), nullable=True),
        sa.Column("condition_json", sa.Text(), nullable=True),
        sa.Column("source_stage_json", sa.Text(), nullable=True),
        sa.Column("data_version", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["chain_id"],
            ["elf_evolution_chain.chain_id"],
            name=op.f("fk_elf_evolution_stage_chain_id_elf_evolution_chain"),
        ),
        sa.ForeignKeyConstraint(
            ["elf_id"],
            ["elf_definition.elf_id"],
            name=op.f("fk_elf_evolution_stage_elf_id_elf_definition"),
        ),
        sa.ForeignKeyConstraint(
            ["evolves_from_elf_id"],
            ["elf_definition.elf_id"],
            name=op.f("fk_elf_evolution_stage_evolves_from_elf_id_elf_definition"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_elf_evolution_stage")),
        sa.UniqueConstraint("chain_id", "elf_id", name="uq_elf_evolution_stage_chain_elf"),
    )
    op.create_index(
        "idx_elf_evolution_stage_chain",
        "elf_evolution_stage",
        ["chain_id", "stage_index"],
        unique=False,
    )
    op.create_index("idx_elf_evolution_stage_elf", "elf_evolution_stage", ["elf_id"], unique=False)


def downgrade() -> None:
    """Drop evolution chain tables."""
    op.drop_index("idx_elf_evolution_stage_elf", table_name="elf_evolution_stage")
    op.drop_index("idx_elf_evolution_stage_chain", table_name="elf_evolution_stage")
    op.drop_table("elf_evolution_stage")
    op.drop_index("idx_elf_evolution_chain_source", table_name="elf_evolution_chain")
    op.drop_table("elf_evolution_chain")
