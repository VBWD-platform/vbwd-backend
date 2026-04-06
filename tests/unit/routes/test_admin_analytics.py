"""Tests for admin analytics routes."""
from unittest.mock import patch, MagicMock
from uuid import uuid4
from vbwd.models.enums import UserRole


class TestAdminAnalyticsDashboard:
    """Tests for admin analytics dashboard endpoint."""

    @patch("plugins.analytics.src.routes.db")
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_dashboard_returns_metrics(
        self, mock_auth_user_repo_class, mock_auth_class, mock_db, client
    ):
        """Dashboard returns expected metrics structure."""
        admin_id = uuid4()

        # Mock admin user
        mock_admin = MagicMock()
        mock_admin.id = admin_id
        mock_admin.status.value = "ACTIVE"
        mock_admin.role = UserRole.ADMIN
        mock_admin.is_admin = True
        mock_auth_user_repo = MagicMock()
        mock_auth_user_repo.find_by_id.return_value = mock_admin
        mock_auth_user_repo_class.return_value = mock_auth_user_repo

        mock_auth = MagicMock()
        mock_auth.verify_token.return_value = str(admin_id)
        mock_auth_class.return_value = mock_auth

        # Mock database session with chained queries
        mock_session = MagicMock()
        mock_db.session = mock_session

        # All queries return scalar values
        mock_query = MagicMock()
        mock_query.scalar.return_value = 100
        mock_query.filter.return_value = mock_query
        mock_session.query.return_value = mock_query

        response = client.get(
            "/api/v1/admin/analytics/dashboard",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.get_json()

        # Verify structure matches frontend expectations
        assert "mrr" in data
        assert "revenue" in data
        assert "user_growth" in data

        # Verify mrr structure
        assert "total" in data["mrr"]
        assert isinstance(data["mrr"]["total"], (int, float))

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_dashboard_requires_admin(
        self, mock_user_repo_class, mock_auth_class, client
    ):
        """Regular user cannot access dashboard."""
        user_id = uuid4()

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.status.value = "ACTIVE"
        mock_user.role = UserRole.USER
        mock_user.is_admin = False

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = mock_user
        mock_user_repo_class.return_value = mock_user_repo

        mock_auth = MagicMock()
        mock_auth.verify_token.return_value = str(user_id)
        mock_auth_class.return_value = mock_auth

        response = client.get(
            "/api/v1/admin/analytics/dashboard",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 403

    def test_dashboard_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        response = client.get("/api/v1/admin/analytics/dashboard")
        assert response.status_code == 401
