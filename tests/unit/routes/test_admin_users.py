"""Tests for admin user routes."""
from unittest.mock import patch, MagicMock
from uuid import uuid4
from vbwd.models.enums import UserRole, UserStatus


class TestAdminListUsers:
    """Tests for admin list users endpoint."""

    @patch("vbwd.routes.admin.users.UserRepository")
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_users_as_admin(
        self, mock_auth_user_repo_class, mock_auth_class, mock_user_repo_class, client
    ):
        """Admin can list users."""
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

        # Mock users list
        mock_users = [
            MagicMock(
                to_dict=lambda: {"id": str(uuid4()), "email": "user1@example.com"}
            ),
            MagicMock(
                to_dict=lambda: {"id": str(uuid4()), "email": "user2@example.com"}
            ),
        ]

        mock_user_repo = MagicMock()
        mock_user_repo.find_all_paginated.return_value = (mock_users, 2)
        mock_user_repo_class.return_value = mock_user_repo

        response = client.get(
            "/api/v1/admin/users/", headers={"Authorization": "Bearer valid_token"}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "users" in data
        assert "total" in data

    @patch("vbwd.routes.admin.users.UserRepository")
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_users_with_pagination(
        self, mock_auth_user_repo_class, mock_auth_class, mock_user_repo_class, client
    ):
        """Pagination parameters work correctly."""
        admin_id = uuid4()

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

        mock_user_repo = MagicMock()
        mock_user_repo.find_all_paginated.return_value = ([], 0)
        mock_user_repo_class.return_value = mock_user_repo

        response = client.get(
            "/api/v1/admin/users/?limit=10&offset=20",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        mock_user_repo.find_all_paginated.assert_called_once()
        call_kwargs = mock_user_repo.find_all_paginated.call_args
        assert call_kwargs[1]["limit"] == 10
        assert call_kwargs[1]["offset"] == 20

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_users_as_regular_user(
        self, mock_user_repo_class, mock_auth_class, client
    ):
        """Regular user cannot list users."""
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
            "/api/v1/admin/users/", headers={"Authorization": "Bearer valid_token"}
        )

        assert response.status_code == 403

    def test_list_users_unauthenticated(self, client):
        """Unauthenticated request returns 401."""
        response = client.get("/api/v1/admin/users/")

        assert response.status_code == 401


class TestAdminGetUser:
    """Tests for admin get user detail endpoint."""

    @patch("vbwd.routes.admin.users.UserRepository")
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_user_detail(
        self, mock_auth_user_repo_class, mock_auth_class, mock_user_repo_class, client
    ):
        """Admin can get user detail."""
        admin_id = uuid4()
        user_id = uuid4()

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

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.to_dict.return_value = {
            "id": str(user_id),
            "email": "user@example.com",
            "status": "active",
        }

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = mock_user
        mock_user_repo_class.return_value = mock_user_repo

        response = client.get(
            f"/api/v1/admin/users/{user_id}",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "user" in data

    @patch("vbwd.routes.admin.users.UserRepository")
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_user_not_found(
        self, mock_auth_user_repo_class, mock_auth_class, mock_user_repo_class, client
    ):
        """404 when user not found."""
        admin_id = uuid4()

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

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = None
        mock_user_repo_class.return_value = mock_user_repo

        response = client.get(
            f"/api/v1/admin/users/{uuid4()}",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 404


class TestAdminUpdateUser:
    """Tests for admin update user endpoint."""

    @patch("vbwd.routes.admin.users.UserRepository")
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_update_user_status(
        self, mock_auth_user_repo_class, mock_auth_class, mock_user_repo_class, client
    ):
        """Admin can update user status."""
        admin_id = uuid4()
        user_id = uuid4()

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

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.status = UserStatus.ACTIVE
        mock_user.to_dict.return_value = {"id": str(user_id), "status": "suspended"}

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = mock_user
        mock_user_repo.save.return_value = mock_user
        mock_user_repo_class.return_value = mock_user_repo

        response = client.put(
            f"/api/v1/admin/users/{user_id}",
            json={"status": "SUSPENDED"},
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200

    @patch("vbwd.routes.admin.users.UserRepository")
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_suspend_user(
        self, mock_auth_user_repo_class, mock_auth_class, mock_user_repo_class, client
    ):
        """Admin can suspend a user."""
        admin_id = uuid4()
        user_id = uuid4()

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

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.status = UserStatus.ACTIVE
        mock_user.to_dict.return_value = {"id": str(user_id), "status": "suspended"}

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = mock_user
        mock_user_repo.save.return_value = mock_user
        mock_user_repo_class.return_value = mock_user_repo

        response = client.post(
            f"/api/v1/admin/users/{user_id}/suspend",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200

    @patch("vbwd.routes.admin.users.UserRepository")
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_activate_user(
        self, mock_auth_user_repo_class, mock_auth_class, mock_user_repo_class, client
    ):
        """Admin can activate a suspended user."""
        admin_id = uuid4()
        user_id = uuid4()

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

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.status = UserStatus.SUSPENDED
        mock_user.to_dict.return_value = {"id": str(user_id), "status": "active"}

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = mock_user
        mock_user_repo.save.return_value = mock_user
        mock_user_repo_class.return_value = mock_user_repo

        response = client.post(
            f"/api/v1/admin/users/{user_id}/activate",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
