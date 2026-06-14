"""Drop ``is_active``/``is_default`` from ``vbwd_currency`` and widen rate (S84).

A CORE migration: it anchors only on the core head
(``20260612_1100_withdraw_tx``) and resolves standalone — no plugin is
involved. Currency is core vocabulary.

S84 makes the core settings JSON the single source of truth for the
active set and the default currency, so the ``is_active``/``is_default``
columns on ``vbwd_currency`` (a second source of truth) are dropped. The
``exchange_rate`` column is widened ``Numeric(10, 6)`` → ``Numeric(18, 8)``
so a re-based rate (e.g. after a USD-base edit) can hold ≥1e-8 precision,
preserving the ≤1e-7 conversion-accuracy guarantee.

Downgrade re-adds the two columns nullable (data is not restored — it now
lives in settings) and narrows the rate back to ``Numeric(10, 6)``.

Revision ID: 20260613_1000_curr_flags
Revises: 20260612_1100_withdraw_tx
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op


revision = "20260613_1000_curr_flags"
down_revision = "20260612_1100_withdraw_tx"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("vbwd_currency", "is_active")
    op.drop_column("vbwd_currency", "is_default")
    op.alter_column(
        "vbwd_currency",
        "exchange_rate",
        existing_type=sa.Numeric(10, 6),
        type_=sa.Numeric(18, 8),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        "vbwd_currency",
        "exchange_rate",
        existing_type=sa.Numeric(18, 8),
        type_=sa.Numeric(10, 6),
        existing_nullable=False,
    )
    op.add_column(
        "vbwd_currency",
        sa.Column("is_default", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "vbwd_currency",
        sa.Column("is_active", sa.Boolean(), nullable=True),
    )
