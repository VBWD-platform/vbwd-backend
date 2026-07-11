"""Add ON DELETE CASCADE to the three core FKs that point at ``vbwd_user``.

Deleting a SUPER_ADMIN / ADMIN user via ``DELETE /api/v1/admin/users/<id>``
raised an unhandled ``IntegrityError`` (HTTP 500). ``UserRepository.delete``
runs a single ``DELETE FROM vbwd_user`` and relies on the database FK cascade,
but three core join / usage tables referenced ``vbwd_user.id`` with the default
``NO ACTION`` and so blocked the delete at statement-end:

    vbwd_user_admin_role.user_id        (the admin-specific blocker)
    vbwd_user_access_level_rel.user_id
    vbwd_feature_usage.user_id

All three rows are user-owned, so ``ON DELETE CASCADE`` is the correct
semantics: removing a user removes their admin-role assignments, access-level
grants, and usage counters.

The two join tables were renamed by earlier migrations (rename_admin_role /
rename_access_level_join), so the Postgres-generated FK constraint names are
not obvious. This migration therefore looks the constraint up from the catalog
by (table, column) and drops+recreates it with ``ondelete="CASCADE"`` — robust
to whatever the constraint is actually called.

Pure CORE migration; resolves standalone ([[project_migration_graph_fragmentation]]).

Revision ID: 20260711_1000_user_fk_ondelete_cascade
Revises: 20260619_1000_outbound_webhooks
Create Date: 2026-07-11
"""
from alembic import op


revision = "20260711_1000_user_fk_ondelete_cascade"
down_revision = "20260619_1000_outbound_webhooks"
branch_labels = None
depends_on = None


# (table, fk-name) for each user-owned reference to vbwd_user.id.
_USER_FK_TABLES = (
    ("vbwd_user_admin_role", "vbwd_user_admin_role_user_id_fkey"),
    ("vbwd_user_access_level_rel", "vbwd_user_access_level_rel_user_id_fkey"),
    ("vbwd_feature_usage", "vbwd_feature_usage_user_id_fkey"),
)


def _drop_existing_user_fk(table_name: str) -> None:
    """Drop whatever FK currently constrains ``<table>.user_id`` to vbwd_user.

    Looks the constraint name up from ``pg_constraint`` so we do not depend on
    the (renamed) generated name being predictable.
    """
    op.execute(
        f"""
DO $$
DECLARE cname text;
BEGIN
  SELECT con.conname INTO cname
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  WHERE rel.relname = '{table_name}' AND con.contype = 'f'
    AND con.conkey = ARRAY[(
      SELECT attnum FROM pg_attribute
      WHERE attrelid = rel.oid AND attname = 'user_id'
    )];
  IF cname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE {table_name} DROP CONSTRAINT %I', cname);
  END IF;
END $$;"""
    )


def upgrade() -> None:
    for table_name, fk_name in _USER_FK_TABLES:
        _drop_existing_user_fk(table_name)
        op.create_foreign_key(
            fk_name,
            table_name,
            "vbwd_user",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for table_name, fk_name in _USER_FK_TABLES:
        _drop_existing_user_fk(table_name)
        op.create_foreign_key(
            fk_name,
            table_name,
            "vbwd_user",
            ["user_id"],
            ["id"],
        )
