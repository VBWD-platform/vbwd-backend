"""Rename the AccessLevel model tables (S94 Slice 6a).

Renames the System-C tables so the names spell out that they model *access
levels* (not "user access levels" — the redundant prefix collided with the
``vbwd_user_*`` user-owned tables and the inverted admin API):

    vbwd_user_access_level             → vbwd_access_level
    vbwd_user_access_level_permissions → vbwd_access_level_permissions

The PK / FK / index constraint names are renamed to the new prefix so the
Postgres-generated names do not drift from the table names. The user-join
``vbwd_user_access_level_rel`` keeps its name (renamed in Slice 5); its FK to
the renamed table follows automatically via ``rename_table``. Pure CORE
migration; resolves standalone ([[project_migration_graph_fragmentation]]).

Revision ID: 20260616_1600_rename_al_model
Revises: 20260616_1500_rename_al_join
Create Date: 2026-06-16
"""
from alembic import op


revision = "20260616_1600_rename_al_model"
down_revision = "20260616_1500_rename_al_join"
branch_labels = None
depends_on = None

OLD = "vbwd_user_access_level"
NEW = "vbwd_access_level"
OLD_PERMS = "vbwd_user_access_level_permissions"
NEW_PERMS = "vbwd_access_level_permissions"

# (old_name, new_name) constraint renames — auto-generated names follow the
# table name, so rename them in lock-step.
_LEVEL_CONSTRAINTS = [
    (f"{OLD}_pkey", f"{NEW}_pkey"),
]

# Indexes on the access-level table (name/slug unique, linked_plan_slug plain).
_LEVEL_INDEXES = [
    (f"ix_{OLD}_name", f"ix_{NEW}_name"),
    (f"ix_{OLD}_slug", f"ix_{NEW}_slug"),
    (f"ix_{OLD}_linked_plan_slug", f"ix_{NEW}_linked_plan_slug"),
]

_PERMS_CONSTRAINTS = [
    (f"{OLD_PERMS}_pkey", f"{NEW_PERMS}_pkey"),
    (
        f"{OLD_PERMS}_user_access_level_id_fkey",
        f"{NEW_PERMS}_user_access_level_id_fkey",
    ),
    (
        f"{OLD_PERMS}_permission_id_fkey",
        f"{NEW_PERMS}_permission_id_fkey",
    ),
]


def upgrade() -> None:
    op.rename_table(OLD, NEW)
    op.rename_table(OLD_PERMS, NEW_PERMS)

    for old_name, new_name in _LEVEL_CONSTRAINTS:
        op.execute(f'ALTER TABLE {NEW} RENAME CONSTRAINT "{old_name}" TO "{new_name}"')
    for old_name, new_name in _LEVEL_INDEXES:
        op.execute(f'ALTER INDEX "{old_name}" RENAME TO "{new_name}"')
    for old_name, new_name in _PERMS_CONSTRAINTS:
        op.execute(
            f'ALTER TABLE {NEW_PERMS} RENAME CONSTRAINT "{old_name}" TO "{new_name}"'
        )


def downgrade() -> None:
    for old_name, new_name in _PERMS_CONSTRAINTS:
        op.execute(
            f'ALTER TABLE {NEW_PERMS} RENAME CONSTRAINT "{new_name}" TO "{old_name}"'
        )
    for old_name, new_name in _LEVEL_INDEXES:
        op.execute(f'ALTER INDEX "{new_name}" RENAME TO "{old_name}"')
    for old_name, new_name in _LEVEL_CONSTRAINTS:
        op.execute(f'ALTER TABLE {NEW} RENAME CONSTRAINT "{new_name}" TO "{old_name}"')

    op.rename_table(NEW_PERMS, OLD_PERMS)
    op.rename_table(NEW, OLD)
