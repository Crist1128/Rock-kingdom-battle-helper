"""Add raw skill description field.

Revision ID: 0008_skill_raw_description
Revises: 0007_battle_runtime_form
Create Date: 2026-07-04
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0008_skill_raw_description"
down_revision: str | None = "0007_battle_runtime_form"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """为技能定义补充爬虫保留的中文原文描述。"""
    op.add_column("skill_definition", sa.Column("raw_description", sa.Text(), nullable=True))


def downgrade() -> None:
    """移除技能中文原文描述字段。"""
    with op.batch_alter_table("skill_definition") as batch_op:
        batch_op.drop_column("raw_description")
