"""Tests for analytics plugin routes."""
from unittest.mock import patch, MagicMock
from uuid import uuid4
from src.models.enums import UserRole
from src.plugins.base import PluginStatus
from src.plugins.config_store import PluginConfigEntry


def _mock_admin_auth(mock_auth_user_repo_class, mock_auth_class):
    """Set up admin auth mocks."""
    admin_id = uuid4()
    mock_admin = MagicMock()
    mock_admin.id = admin_id
    mock_admin.status.value = "ACTIVE"
    mock_admin.role = UserRole.ADMIN

    mock_auth_user_repo = MagicMock()
    mock_auth_user_repo.find_by_id.return_value = mock_admin
    mock_auth_user_repo_class.return_value = mock_auth_user_repo

    mock_auth = MagicMock()
    mock_auth.verify_token.return_value = str(admin_id)
    mock_auth_class.return_value = mock_auth


class TestActiveSessions:
    """Tests for GET /api/v1/plugins/analytics/active-sessions."""

    @patch("src.middleware.auth.AuthService")
    @patch("src.middleware.auth.UserRepository")
    def test_returns_active_sessions_when_enabled(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        # Mock config_store to report analytics as enabled
        mock_store = MagicMock()
        mock_store.get_by_name.return_value = PluginConfigEntry(
            plugin_name="analytics", status="enabled"
        )
        app.config_store = mock_store

        response = client.get(
            "/api/v1/plugins/analytics/active-sessions",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "count" in data
        assert "source" in data
        assert data["source"] == "plugin"

    @patch("src.middleware.auth.AuthService")
    @patch("src.middleware.auth.UserRepository")
    def test_returns_404_when_disabled(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        mock_store = MagicMock()
        mock_store.get_by_name.return_value = PluginConfigEntry(
            plugin_name="analytics", status="disabled"
        )
        app.config_store = mock_store

        response = client.get(
            "/api/v1/plugins/analytics/active-sessions",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 404

    @patch("src.middleware.auth.AuthService")
    @patch("src.middleware.auth.UserRepository")
    def test_requires_admin_role(self, mock_repo_class, mock_auth_class, app, client):
        """Non-admin users should get 403."""
        user_id = uuid4()
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.status.value = "ACTIVE"
        mock_user.role = UserRole.USER

        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = mock_user
        mock_repo_class.return_value = mock_repo

        mock_auth = MagicMock()
        mock_auth.verify_token.return_value = str(user_id)
        mock_auth_class.return_value = mock_auth

        response = client.get(
            "/api/v1/plugins/analytics/active-sessions",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 403
