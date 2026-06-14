"""Replace the native ``userrole`` enum with the ``vbwd_user_role`` lookup table.

A CORE migration: it anchors only on the current core head
(``20260613_1400_user_account_type``) and resolves standalone — no plugin is
involved.

What it does, in order:
  1. CREATE the ``vbwd_user_role`` lookup table (string slug PK + display name).
     NOTE the *singular* name — the plural ``vbwd_user_roles`` is the unrelated
     RBAC user-role join table that already exists.
  2. Seed the six canonical rows, idempotently (``ON CONFLICT DO NOTHING``).
     The slugs match the ``UserRole`` enum values exactly, so existing
     ``vbwd_user.role`` values map 1:1.
  3. Convert ``vbwd_user.role`` from the native ``userrole`` enum to
     ``VARCHAR(32)`` preserving every existing value (``USING role::text``).
  4. Add the foreign key from ``vbwd_user.role`` to ``vbwd_user_role.id``.
  5. DROP the now-unused native ``userrole`` enum type.

Downgrade reverses it: recreate the enum (incl. ``GUEST`` and ``BOT``), drop
the FK, convert the column back to the enum, drop the lookup table.

Validate up -> down -> up.

Revision ID: 20260613_1500_user_role_lookup
Revises: 20260613_1400_user_account_type
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op


revision = "20260613_1500_user_role_lookup"
down_revision = "20260613_1400_user_account_type"
branch_labels = None
depends_on = None


# Canonical rows — the slug PK is the capitalised enum value, the name is the
# title-cased display label. Kept in the migration as literals (migrations must
# be self-contained / not import live application code), mirroring the single
# source of truth in ``vbwd.models.user_role.canonical_role_rows``.
_CANONICAL_ROLES = [
    ("SUPER_ADMIN", "Super Admin"),
    ("ADMIN", "Admin"),
    ("USER", "User"),
    ("VENDOR", "Vendor"),
    ("BOT", "Bot"),
    ("GUEST", "Guest"),
]

_ENUM_NAME = "userrole"
_ENUM_VALUES = tuple(slug for slug, _ in _CANONICAL_ROLES)


def upgrade():
    op.create_table(
        "vbwd_user_role",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
    )

    rows_sql = ", ".join(f"('{slug}', '{name}')" for slug, name in _CANONICAL_ROLES)
    op.execute(
        f"INSERT INTO vbwd_user_role (id, name) VALUES {rows_sql} "
        "ON CONFLICT (id) DO NOTHING"
    )

    # Native enum -> varchar, preserving existing values verbatim.
    op.execute(
        "ALTER TABLE vbwd_user ALTER COLUMN role TYPE varchar(32) " "USING role::text"
    )

    op.create_foreign_key(
        "fk_vbwd_user_role",
        "vbwd_user",
        "vbwd_user_role",
        ["role"],
        ["id"],
    )

    op.execute(f"DROP TYPE {_ENUM_NAME}")


def downgrade():
    enum_values_sql = ", ".join(f"'{value}'" for value in _ENUM_VALUES)
    op.execute(f"CREATE TYPE {_ENUM_NAME} AS ENUM ({enum_values_sql})")

    op.drop_constraint("fk_vbwd_user_role", "vbwd_user", type_="foreignkey")

    op.execute(
        f"ALTER TABLE vbwd_user ALTER COLUMN role TYPE {_ENUM_NAME} "
        f"USING role::{_ENUM_NAME}"
    )

    op.drop_table("vbwd_user_role")
