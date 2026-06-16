"""Rename the System-B admin-role tables for clarity (S94 Slice 4).

Renames the three RBAC tables that gate ``/admin`` so the table names spell out
that they are admin roles (distinct from the coarse ``vbwd_user_role`` lookup
and the ``vbwd_user_access_level`` system that gates ``/user``):

    vbwd_role             → vbwd_admin_role
    vbwd_role_permissions → vbwd_admin_role_permissions
    vbwd_user_roles       → vbwd_user_admin_role

The PK / FK / index constraint names are also renamed to the new prefix so the
Postgres-generated names do not drift from the table names. A pure CORE
migration; resolves standalone ([[project_migration_graph_fragmentation]]).

Revision ID: 20260616_1400_rename_admin_role
Revises: 20260616_1300_drop_user_case
Create Date: 2026-06-16
"""
from alembic import op


revision = "20260616_1400_rename_admin_role"
down_revision = "20260616_1300_drop_user_case"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("vbwd_role", "vbwd_admin_role")
    op.rename_table("vbwd_role_permissions", "vbwd_admin_role_permissions")
    op.rename_table("vbwd_user_roles", "vbwd_user_admin_role")

    # vbwd_admin_role: pk + unique indexes
    op.execute(
        "ALTER TABLE vbwd_admin_role "
        "RENAME CONSTRAINT vbwd_role_pkey TO vbwd_admin_role_pkey"
    )
    op.execute("ALTER INDEX ix_vbwd_role_name RENAME TO ix_vbwd_admin_role_name")
    op.execute("ALTER INDEX ix_vbwd_role_slug RENAME TO ix_vbwd_admin_role_slug")

    # vbwd_admin_role_permissions: pk + fks
    op.execute(
        "ALTER TABLE vbwd_admin_role_permissions "
        "RENAME CONSTRAINT vbwd_role_permissions_pkey "
        "TO vbwd_admin_role_permissions_pkey"
    )
    op.execute(
        "ALTER TABLE vbwd_admin_role_permissions "
        "RENAME CONSTRAINT vbwd_role_permissions_role_id_fkey "
        "TO vbwd_admin_role_permissions_role_id_fkey"
    )
    op.execute(
        "ALTER TABLE vbwd_admin_role_permissions "
        "RENAME CONSTRAINT vbwd_role_permissions_permission_id_fkey "
        "TO vbwd_admin_role_permissions_permission_id_fkey"
    )

    # vbwd_user_admin_role: pk + fks
    op.execute(
        "ALTER TABLE vbwd_user_admin_role "
        "RENAME CONSTRAINT vbwd_user_roles_pkey TO vbwd_user_admin_role_pkey"
    )
    op.execute(
        "ALTER TABLE vbwd_user_admin_role "
        "RENAME CONSTRAINT vbwd_user_roles_user_id_fkey "
        "TO vbwd_user_admin_role_user_id_fkey"
    )
    op.execute(
        "ALTER TABLE vbwd_user_admin_role "
        "RENAME CONSTRAINT vbwd_user_roles_role_id_fkey "
        "TO vbwd_user_admin_role_role_id_fkey"
    )


def downgrade() -> None:
    # Reverse the constraint/index renames first, then the table renames.
    op.execute(
        "ALTER TABLE vbwd_user_admin_role "
        "RENAME CONSTRAINT vbwd_user_admin_role_role_id_fkey "
        "TO vbwd_user_roles_role_id_fkey"
    )
    op.execute(
        "ALTER TABLE vbwd_user_admin_role "
        "RENAME CONSTRAINT vbwd_user_admin_role_user_id_fkey "
        "TO vbwd_user_roles_user_id_fkey"
    )
    op.execute(
        "ALTER TABLE vbwd_user_admin_role "
        "RENAME CONSTRAINT vbwd_user_admin_role_pkey TO vbwd_user_roles_pkey"
    )

    op.execute(
        "ALTER TABLE vbwd_admin_role_permissions "
        "RENAME CONSTRAINT vbwd_admin_role_permissions_permission_id_fkey "
        "TO vbwd_role_permissions_permission_id_fkey"
    )
    op.execute(
        "ALTER TABLE vbwd_admin_role_permissions "
        "RENAME CONSTRAINT vbwd_admin_role_permissions_role_id_fkey "
        "TO vbwd_role_permissions_role_id_fkey"
    )
    op.execute(
        "ALTER TABLE vbwd_admin_role_permissions "
        "RENAME CONSTRAINT vbwd_admin_role_permissions_pkey "
        "TO vbwd_role_permissions_pkey"
    )

    op.execute("ALTER INDEX ix_vbwd_admin_role_slug RENAME TO ix_vbwd_role_slug")
    op.execute("ALTER INDEX ix_vbwd_admin_role_name RENAME TO ix_vbwd_role_name")
    op.execute(
        "ALTER TABLE vbwd_admin_role "
        "RENAME CONSTRAINT vbwd_admin_role_pkey TO vbwd_role_pkey"
    )

    op.rename_table("vbwd_user_admin_role", "vbwd_user_roles")
    op.rename_table("vbwd_admin_role_permissions", "vbwd_role_permissions")
    op.rename_table("vbwd_admin_role", "vbwd_role")
