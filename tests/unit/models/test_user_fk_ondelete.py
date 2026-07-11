"""Model-level guard for the ``ON DELETE CASCADE`` fix (S — admin-delete 500).

Deleting an ADMIN / SUPER_ADMIN user 500'd because three core tables held a FK
to ``vbwd_user.id`` with no ``ondelete``. The Alembic migration fixes existing
databases; these assertions guard the *model* definitions so a fresh
``create_all`` install is correct too — introspecting SQLAlchemy metadata only
(no DB, no app), so the check is fast and order-independent.
"""
from vbwd.models.feature_usage import FeatureUsage
from vbwd.models.role import user_roles
from vbwd.models.user_access_level import user_user_access_levels


def _user_fk_ondelete(table, column_name: str) -> str:
    column = table.c[column_name]
    user_fks = [fk for fk in column.foreign_keys if fk.column.table.name == "vbwd_user"]
    assert len(user_fks) == 1, f"expected one FK to vbwd_user on {column}"
    return user_fks[0].ondelete


def test_user_admin_role_user_id_cascades():
    assert _user_fk_ondelete(user_roles, "user_id") == "CASCADE"


def test_user_access_level_rel_user_id_cascades():
    assert _user_fk_ondelete(user_user_access_levels, "user_id") == "CASCADE"


def test_feature_usage_user_id_cascades():
    assert _user_fk_ondelete(FeatureUsage.__table__, "user_id") == "CASCADE"
