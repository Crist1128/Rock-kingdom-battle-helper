"""relax estimate evidence source reference

Revision ID: 0005_relax_estimate_evidence_source
Revises: 0004_enemy_panel_estimates
Create Date: 2026-06-08 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_relax_estimate_evidence_source"
down_revision: str | None = "0004_enemy_panel_estimates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """允许 Observation 自生成 ID 作为估计 evidence 来源。"""
    with op.batch_alter_table("enemy_panel_estimate_evidence", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "fk_enemy_panel_estimate_evidence_source_event_id_battle_event",
            type_="foreignkey",
        )


def downgrade() -> None:
    """恢复 source_event_id 对 battle_event 的外键约束。"""
    with op.batch_alter_table("enemy_panel_estimate_evidence", recreate="always") as batch_op:
        batch_op.create_foreign_key(
            "fk_enemy_panel_estimate_evidence_source_event_id_battle_event",
            "battle_event",
            ["source_event_id"],
            ["event_id"],
        )
