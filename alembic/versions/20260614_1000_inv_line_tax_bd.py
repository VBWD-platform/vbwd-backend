"""S85.4 — per-line tax disclosure columns on the invoice line item.

Adds ``net_amount``, ``tax_amount`` (``Numeric(10,2)``) and ``tax_breakdown``
(JSONB, default empty list) to ``vbwd_invoice_line_item`` so the invoice tax
disclosure can render real per-rate VAT lines and net/Σtax/gross totals.
``total_price`` stays the gross. These are generic fields the plugins populate
from the core ``Price`` VO — core stays agnostic.

This is a CORE migration: it anchors on the core chain's own prior head and
declares ``depends_on = None`` so it resolves on a core-only install.

Revision ID: 20260614_1000_inv_line_tax_bd
Revises: 20260613_1500_user_role_lookup
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260614_1000_inv_line_tax_bd"
down_revision = "20260613_1500_user_role_lookup"
branch_labels = None
depends_on = None

TABLE = "vbwd_invoice_line_item"


def upgrade():
    op.add_column(
        TABLE,
        sa.Column("net_amount", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "tax_amount",
            sa.Numeric(10, 2),
            nullable=True,
            server_default="0",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "tax_breakdown",
            JSONB,
            nullable=True,
            server_default="[]",
        ),
    )


def downgrade():
    op.drop_column(TABLE, "tax_breakdown")
    op.drop_column(TABLE, "tax_amount")
    op.drop_column(TABLE, "net_amount")
