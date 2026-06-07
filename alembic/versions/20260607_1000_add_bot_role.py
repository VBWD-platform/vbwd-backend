"""Add the ``BOT`` value to the core ``userrole`` Postgres enum (S60).

A CORE migration: it anchors only on the core head
(``20260602_1000_seed_marker``) and resolves standalone — no plugin is
involved. The new role lets plugins (e.g. meinchat) provision
server-authored, non-privileged sender identities.

Postgres ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction
block, so we use Alembic's autocommit block to step outside the
migration's surrounding transaction for that one statement. ``IF NOT
EXISTS`` makes the upgrade idempotent.

Downgrade is a documented no-op: Postgres cannot drop an enum value, and
the value is harmless to leave in place.

Revision ID: 20260607_1000_add_bot_role
Revises: 20260602_1000_seed_marker
Create Date: 2026-06-07
"""
from alembic import op


revision = "20260607_1000_add_bot_role"
down_revision = "20260602_1000_seed_marker"
branch_labels = None
depends_on = None


def upgrade():
    # ADD VALUE cannot run inside a transaction → autocommit block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'BOT'")


def downgrade():
    # Postgres cannot drop a value from an enum type; leaving 'BOT' in
    # place is harmless. Documented no-op.
    pass
