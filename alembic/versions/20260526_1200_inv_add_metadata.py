"""Add generic ``metadata`` JSON column to vbwd_user_invoice.

Payment plugins write their per-method capture details under their own
top-level key (e.g. ``{"stripe": {"transaction_id": "..."}}`` /
``{"tokens_paid": {"amount": 600}}``) so the invoice detail can render
plugin-specific info without core knowing any method's shape — agnostic.

Revision ID: 20260526_1200_inv_add_metadata
Revises: 20260525_1000_inv_drop_sub_fk
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa


revision = "20260526_1200_inv_add_metadata"
down_revision = "20260525_1000_inv_drop_sub_fk"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vbwd_user_invoice",
        sa.Column("metadata", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("vbwd_user_invoice", "metadata")
