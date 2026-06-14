"""Add the ``GUEST`` value to the core ``userrole`` Postgres enum (S86.1 D-core).

A CORE migration: it anchors only on the current core head
(``20260613_1200_tb_price_float``) and resolves standalone — no plugin is
involved. The new role is a server-provisioned, public-scope-only identity
(e.g. a widget visitor) that plugins provision in S86.3.

Postgres ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction
block, so we use Alembic's autocommit block (same pattern as
``20260607_1000_add_bot_role``) to step outside the migration's surrounding
transaction for that one statement. ``IF NOT EXISTS`` makes the upgrade
idempotent.

Downgrade is a documented no-op: Postgres cannot drop an enum value, and
the value is harmless to leave in place.

Revision ID: 20260613_1300_add_guest_role
Revises: 20260613_1200_tb_price_float
Create Date: 2026-06-13
"""
from alembic import op


revision = "20260613_1300_add_guest_role"
down_revision = "20260613_1200_tb_price_float"
branch_labels = None
depends_on = None


def upgrade():
    # ADD VALUE cannot run inside a transaction → autocommit block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'GUEST'")


def downgrade():
    # Postgres cannot drop a value from an enum type; leaving 'GUEST' in
    # place is harmless. Documented no-op.
    pass
