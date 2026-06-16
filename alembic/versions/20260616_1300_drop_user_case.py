"""Drop the orphan ``vbwd_user_case`` table + ``usercasestatus`` enum (S94 S2).

``UserCase`` was created in the big-bang migration but never wired — zero
routes/services reference it; the only consumer was an infra "table exists"
assertion. A pure CORE migration; resolves standalone
([[project_migration_graph_fragmentation]]).

Revision ID: 20260616_1300_drop_user_case
Revises: 20260616_1200_drop_balance
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa


revision = "20260616_1300_drop_user_case"
down_revision = "20260616_1200_drop_balance"
branch_labels = None
depends_on = None

TABLE = "vbwd_user_case"
ENUM = "usercasestatus"


def upgrade() -> None:
    op.drop_index(op.f("ix_vbwd_user_case_user_id"), table_name=TABLE)
    op.drop_index(op.f("ix_vbwd_user_case_status"), table_name=TABLE)
    op.drop_table(TABLE)
    op.execute(f"DROP TYPE IF EXISTS {ENUM}")


def downgrade() -> None:
    # Recreate the original shape from the big-bang DDL. The inline sa.Enum
    # recreates the native ``usercasestatus`` type.
    op.create_table(
        TABLE,
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("date_started", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "ACTIVE", "COMPLETED", "ARCHIVED", name=ENUM),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["vbwd_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vbwd_user_case_status"), TABLE, ["status"], unique=False)
    op.create_index(op.f("ix_vbwd_user_case_user_id"), TABLE, ["user_id"], unique=False)
