"""Tests for RBAC service."""
import pytest
from unittest.mock import Mock
from uuid import uuid4
from vbwd.services.rbac_service import RBACService


class TestRBACService:
    """Test cases for RBACService."""

    @pytest.fixture
    def mock_role_repo(self):
        """Create mock role repository."""
        return Mock()

    @pytest.fixture
    def rbac_service(self, mock_role_repo):
        """Create RBAC service with mock repository."""
        return RBACService(mock_role_repo)

    def test_dead_check_methods_removed(self, rbac_service):
        """S94 Slice 3 — the parallel permission-check path was removed; the
        single live check is ``User.has_permission``. RBACService keeps only
        its assign/grant + read helpers.
        """
        for dead in ("has_permission", "has_any_permission", "has_all_permissions"):
            assert not hasattr(rbac_service, dead), (
                f"RBACService.{dead} should have been removed "
                "(live check is User.has_permission)."
            )

    def test_assign_role_delegates_to_repository(self, rbac_service, mock_role_repo):
        """Role assignment is delegated to repository."""
        user_id = uuid4()
        mock_role_repo.assign_role.return_value = True

        result = rbac_service.assign_role(user_id, "moderator")

        assert result is True
        mock_role_repo.assign_role.assert_called_once_with(user_id, "moderator")

    def test_revoke_role_delegates_to_repository(self, rbac_service, mock_role_repo):
        """Role revocation is delegated to repository."""
        user_id = uuid4()
        mock_role_repo.revoke_role.return_value = True

        result = rbac_service.revoke_role(user_id, "moderator")

        assert result is True
        mock_role_repo.revoke_role.assert_called_once_with(user_id, "moderator")

    def test_get_user_permissions_returns_set(self, rbac_service, mock_role_repo):
        """Returns set of permission names."""
        user_id = uuid4()
        expected = {"users.view", "reports.view"}
        mock_role_repo.get_user_permissions.return_value = expected

        result = rbac_service.get_user_permissions(user_id)

        assert result == expected

    def test_get_user_roles_returns_role_names(self, rbac_service, mock_role_repo):
        """Returns list of role names."""
        user_id = uuid4()
        mock_role1 = Mock()
        mock_role1.name = "user"
        mock_role2 = Mock()
        mock_role2.name = "moderator"
        mock_role_repo.get_user_roles.return_value = [mock_role1, mock_role2]

        result = rbac_service.get_user_roles(user_id)

        assert result == ["user", "moderator"]

    def test_is_admin_returns_true_for_admin(self, rbac_service, mock_role_repo):
        """Returns True for admin user."""
        user_id = uuid4()
        mock_role_repo.user_has_role.return_value = True

        result = rbac_service.is_admin(user_id)

        assert result is True
        mock_role_repo.user_has_role.assert_called_with(user_id, "admin")

    def test_is_admin_returns_false_for_non_admin(self, rbac_service, mock_role_repo):
        """Returns False for non-admin user."""
        user_id = uuid4()
        mock_role_repo.user_has_role.return_value = False

        result = rbac_service.is_admin(user_id)

        assert result is False
