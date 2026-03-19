"""Add AUTHORIZED to InvoiceStatus enum.

Revision ID: 20260319_authorized
Create Date: 2026-03-19
"""
from alembic import op

revision = "20260319_authorized"
down_revision = None
branch_labels = ("authorized_status",)
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE invoicestatus ADD VALUE IF NOT EXISTS 'AUTHORIZED'")


def downgrade() -> None:
    pass
