"""S52.4 — the API-key permissions are in the core catalogues.

``api_keys.manage`` is a core admin permission; ``manage_api`` is a core
user-facing permission. Both must be seedable so an admin can grant them.
"""
from vbwd.routes.admin.access import CORE_PERMISSIONS, CORE_USER_PERMISSIONS


def test_api_keys_manage_in_core_admin_permissions():
    keys = {entry["key"] for entry in CORE_PERMISSIONS}
    assert "api_keys.manage" in keys


def test_manage_api_in_core_user_permissions():
    keys = {entry["key"] for entry in CORE_USER_PERMISSIONS}
    assert "manage_api" in keys


def test_rbac_seeder_creates_manage_api_permission_row():
    """The seeder flattens core user permissions into Permission rows so an
    admin can assign ``manage_api`` to a user access level."""
    from unittest.mock import MagicMock

    from vbwd.services import rbac_seeder

    seen_names = []

    def fake_upsert(session, name):
        seen_names.append(name)
        return True

    original = rbac_seeder._upsert_permission
    rbac_seeder._upsert_permission = fake_upsert  # type: ignore[assignment]
    try:
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        rbac_seeder.seed_default_rbac(session, plugin_manager=_EmptyManager())
    finally:
        rbac_seeder._upsert_permission = original  # type: ignore[assignment]

    assert "manage_api" in seen_names


class _EmptyManager:
    def get_enabled_plugins(self):
        return []
