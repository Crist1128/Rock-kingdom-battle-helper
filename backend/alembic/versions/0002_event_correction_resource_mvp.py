"""add event correction columns for MVP audit

Revision ID: 0002_event_correction_resource_mvp
Revises: 0001_initial_schema
Create Date: 2026-05-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_event_correction_resource_mvp"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为已有本地数据库补充事件排序与纠错字段。"""
    with op.batch_alter_table("battle_event") as batch_op:
        batch_op.add_column(sa.Column("action_order", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("corrected_event_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("is_voided", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.drop_index("idx_battle_event_battle_turn", table_name="battle_event")
    op.create_index(
        "idx_battle_event_battle_turn",
        "battle_event",
        ["battle_id", "turn_number", "action_order", "created_at"],
    )


def downgrade() -> None:
    """回滚事件排序与纠错字段。"""
    op.drop_index("idx_battle_event_battle_turn", table_name="battle_event")
    op.create_index(
        "idx_battle_event_battle_turn",
        "battle_event",
        ["battle_id", "turn_number", "created_at"],
    )
    with op.batch_alter_table("battle_event") as batch_op:
        batch_op.drop_column("is_voided")
        batch_op.drop_column("corrected_event_id")
        batch_op.drop_column("action_order")
