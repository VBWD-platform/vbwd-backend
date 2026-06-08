"""Remove the redundant ``user`` system RBAC role.

A CORE migration: it anchors only on the core head
(``20260607_1000_add_bot_role``) and resolves standalone — no plugin is
involved.

The seeder used to upsert three system roles (``super_admin``, ``admin``,
``user``). The ``user`` role held **no permissions** and was never assigned
(a regular account is identified by the ``UserRole.USER`` enum on the user
record, not by this RBAC role). Listed in the admin Access-Levels UI it only
created ambiguity, so it is removed here and dropped from ``DEFAULT_ROLES``.

Idempotent: deletes the role only if a system ``user`` role exists, after
clearing any stray ``vbwd_user_roles`` / ``vbwd_role_permissions`` links
(expected zero). Downgrade re-inserts a permission-less system ``user`` role.

Revision ID: 20260608_1000_remove_user_role
Revises: 20260607_1000_add_bot_role
Create Date: 2026-06-08
"""
from alembic import op


revision = "20260608_1000_remove_user_role"
down_revision = "20260607_1000_add_bot_role"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "DELETE FROM vbwd_user_roles WHERE role_id IN "
        "(SELECT id FROM vbwd_role WHERE slug = 'user' AND is_system = true)"
    )
    op.execute(
        "DELETE FROM vbwd_role_permissions WHERE role_id IN "
        "(SELECT id FROM vbwd_role WHERE slug = 'user' AND is_system = true)"
    )
    op.execute("DELETE FROM vbwd_role WHERE slug = 'user' AND is_system = true")


def downgrade():
    # Re-create the permission-less system ``user`` role (idempotent).
    op.execute(
        "INSERT INTO vbwd_role "
        "(id, name, slug, description, is_system, created_at, updated_at, version) "
        "SELECT gen_random_uuid(), 'user', 'user', "
        "'Standard user with no admin permissions.', true, now(), now(), 1 "
        "WHERE NOT EXISTS "
        "(SELECT 1 FROM vbwd_role WHERE slug = 'user')"
    )
