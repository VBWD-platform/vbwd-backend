"""Convert vbwd_user_invoice.metadata from JSON to JSONB.

Postgres' ``json`` type has no equality operator, so any ``SELECT DISTINCT``
involving the invoice table (e.g. the admin subscription detail endpoint,
which joins invoices via line items and DISTINCTs them) throws::

    psycopg2.errors.UndefinedFunction: could not identify an equality
    operator for type json

``jsonb`` has the operator and is the more common Postgres choice for app
metadata anyway (faster lookups, GIN-indexable). This migration keeps the
column name + nullability, only swaps the storage type via ``USING``.

Also converts ``vbwd_invoice_line_item.metadata`` for the same reason —
the same query joins through it.

Revision ID: 20260526_2200_inv_metadata_to_jsonb
Revises: 20260526_1200_inv_add_metadata
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa


revision = "20260526_2200_md_jsonb"
down_revision = "20260526_1200_inv_add_metadata"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE vbwd_user_invoice "
        "ALTER COLUMN metadata TYPE jsonb USING metadata::jsonb"
    )
    op.execute(
        "ALTER TABLE vbwd_invoice_line_item "
        "ALTER COLUMN metadata TYPE jsonb USING metadata::jsonb"
    )


def downgrade():
    op.execute(
        "ALTER TABLE vbwd_user_invoice "
        "ALTER COLUMN metadata TYPE json USING metadata::json"
    )
    op.execute(
        "ALTER TABLE vbwd_invoice_line_item "
        "ALTER COLUMN metadata TYPE json USING metadata::json"
    )
