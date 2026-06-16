"""Rename the access-level user-join table (S94 Slice 5).

``vbwd_user_user_access_levels`` -> ``vbwd_user_access_level_rel`` (matching the
S73 ``vbwd_user_group_rel`` convention). PK/FK constraint names are renamed to
the new prefix so Postgres names don't drift. Pure CORE migration; resolves
standalone ([[project_migration_graph_fragmentation]]).

Revision ID: 20260616_1500_rename_al_join
Revises: 20260616_1400_rename_admin_role
Create Date: 2026-06-16
"""
from alembic import op


revision = "20260616_1500_rename_al_join"
down_revision = "20260616_1400_rename_admin_role"
branch_labels = None
depends_on = None

OLD = "vbwd_user_user_access_levels"
NEW = "vbwd_user_access_level_rel"

# (old_constraint, new_constraint) — auto-generated PK/FK names follow the
# table name; rename them in lock-step so they don't keep the legacy prefix.
_CONSTRAINTS = [
    (f"{OLD}_pkey", f"{NEW}_pkey"),
    (f"{OLD}_user_id_fkey", f"{NEW}_user_id_fkey"),
    (
        f"{OLD}_user_access_level_id_fkey",
        f"{NEW}_user_access_level_id_fkey",
    ),
]


def upgrade() -> None:
    op.rename_table(OLD, NEW)
    for old_name, new_name in _CONSTRAINTS:
        op.execute(f'ALTER TABLE {NEW} RENAME CONSTRAINT "{old_name}" TO "{new_name}"')


def downgrade() -> None:
    for old_name, new_name in _CONSTRAINTS:
        op.execute(f'ALTER TABLE {NEW} RENAME CONSTRAINT "{new_name}" TO "{old_name}"')
    op.rename_table(NEW, OLD)
