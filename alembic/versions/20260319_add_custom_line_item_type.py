"""Add CUSTOM line item type and metadata column.

Revision ID: 20260319_custom_lineitem
Revises: None (independent head)
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa

revision = "20260319_custom_lineitem"
down_revision = None
branch_labels = ("custom_lineitem",)
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE lineitemtype ADD VALUE IF NOT EXISTS 'CUSTOM'")
    op.add_column(
        "invoice_line_item",
        sa.Column("metadata", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoice_line_item", "metadata")
