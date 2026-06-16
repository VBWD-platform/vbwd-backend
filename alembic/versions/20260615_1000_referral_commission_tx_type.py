"""Add the ``REFERRAL_COMMISSION`` value to the core ``tokentransactiontype`` enum (S92 Track B).

A CORE migration: it anchors only on the core head
(``20260614_1000_inv_line_tax_bd``) and resolves standalone — no plugin is
involved. The value is generic ledger vocabulary (a token commission paid to a
referral coupon's issuer on redemption), written by the referral plugin through
core ``TokenService`` — the same pattern as ``WITHDRAW``
(``20260612_1100_withdraw_tx_type``).

Postgres ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction block, so
we use Alembic's autocommit block. ``IF NOT EXISTS`` makes the upgrade
idempotent.

Downgrade is a documented no-op: Postgres cannot drop an enum value, and the
value is harmless to leave in place.

Revision ID: 20260615_1000_referral_commission_tx
Revises: 20260614_1000_inv_line_tax_bd
Create Date: 2026-06-15
"""
from alembic import op


revision = "20260615_1000_referral_commission_tx"
down_revision = "20260614_1000_inv_line_tax_bd"
branch_labels = None
depends_on = None


def upgrade():
    # ADD VALUE cannot run inside a transaction → autocommit block.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE tokentransactiontype "
            "ADD VALUE IF NOT EXISTS 'REFERRAL_COMMISSION'"
        )


def downgrade():
    # Postgres cannot drop a value from an enum type; leaving
    # 'REFERRAL_COMMISSION' in place is harmless. Documented no-op.
    pass
