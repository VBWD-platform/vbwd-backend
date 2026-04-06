"""Unit tests for access management helpers — Sprint 12b."""
from unittest.mock import MagicMock, patch


from vbwd.routes.admin.access import _assign_permissions, CORE_PERMISSIONS


class TestAssignPermissions:
    """Test _assign_permissions helper."""

    def test_assigns_existing_permission(self):
        role = MagicMock()
        role.permissions = MagicMock()
        role.permissions.clear = MagicMock()
        role.permissions.append = MagicMock()

        perm = MagicMock()
        perm.name = "users.view"

        with patch("vbwd.routes.admin.access.db") as mock_db:
            mock_db.session.query.return_value.filter_by.return_value.first.return_value = (
                perm
            )
            _assign_permissions(role, ["users.view"])

        role.permissions.clear.assert_called_once()
        role.permissions.append.assert_called_once_with(perm)

    def test_creates_missing_permission(self):
        role = MagicMock()
        role.permissions = MagicMock()
        role.permissions.clear = MagicMock()
        role.permissions.append = MagicMock()

        with patch("vbwd.routes.admin.access.db") as mock_db:
            mock_db.session.query.return_value.filter_by.return_value.first.return_value = (
                None
            )
            mock_db.session.add = MagicMock()
            mock_db.session.flush = MagicMock()
            _assign_permissions(role, ["shop.products.manage"])

        role.permissions.clear.assert_called_once()
        role.permissions.append.assert_called_once()
        mock_db.session.add.assert_called_once()


class TestCorePermissions:
    """Test core permission definitions."""

    def test_core_permissions_not_empty(self):
        assert len(CORE_PERMISSIONS) > 0

    def test_core_permissions_have_required_fields(self):
        for perm in CORE_PERMISSIONS:
            assert "key" in perm
            assert "label" in perm
            assert "group" in perm

    def test_settings_system_exists(self):
        keys = [p["key"] for p in CORE_PERMISSIONS]
        assert "settings.system" in keys

    def test_users_permissions_exist(self):
        keys = [p["key"] for p in CORE_PERMISSIONS]
        assert "users.view" in keys
        assert "users.manage" in keys
