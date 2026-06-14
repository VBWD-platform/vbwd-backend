"""Add the ``WITHDRAW`` value to the core ``tokentransactiontype`` enum (S79 D5).

A CORE migration: it anchors only on the core head
(``20260610_device_token``) and resolves standalone — no plugin is
involved. The value is generic ledger vocabulary (a withdraw-to-money
debit/credit), written by the withdraw plugin through core
``TokenService``.

Postgres ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction
block, so we use Alembic's autocommit block (same pattern as
``20260607_1000_add_bot_role``). ``IF NOT EXISTS`` makes the upgrade
idempotent.

Downgrade is a documented no-op: Postgres cannot drop an enum value,
and the value is harmless to leave in place.

Revision ID: 20260612_1100_withdraw_tx
Revises: 20260610_device_token
Create Date: 2026-06-12
"""
from alembic import op


revision = "20260612_1100_withdraw_tx"
down_revision = "20260610_device_token"
branch_labels = None
depends_on = None


def upgrade():
    # ADD VALUE cannot run inside a transaction → autocommit block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE tokentransactiontype ADD VALUE IF NOT EXISTS 'WITHDRAW'")


def downgrade():
    # Postgres cannot drop a value from an enum type; leaving 'WITHDRAW'
    # in place is harmless. Documented no-op.
    pass
