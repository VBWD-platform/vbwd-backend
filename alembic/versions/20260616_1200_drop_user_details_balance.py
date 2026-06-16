"""Drop the dead ``vbwd_user_details.balance`` column (S94 Slice 1).

The column was written only by the admin user-update path and read only in
``UserDetails.to_dict``; it was never part of any user-facing schema. Live
money is ``UserTokenBalance`` (``vbwd_user_token_balance``), untouched here.
A pure CORE migration — no plugin FK, resolves standalone
([[project_migration_graph_fragmentation]]).

Revision ID: 20260616_1200_drop_balance
Revises: 20260615_1100_llm_connection
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa


revision = "20260616_1200_drop_balance"
down_revision = "20260615_1100_llm_connection"
branch_labels = None
depends_on = None

TABLE = "vbwd_user_details"
COLUMN = "balance"


def upgrade() -> None:
    op.drop_column(TABLE, COLUMN)


def downgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            COLUMN,
            sa.Numeric(precision=10, scale=2),
            nullable=False,
            server_default="0.00",
        ),
    )
