"""Unit tests for admin user-group routes (S73).

CRUD + bulk-delete are gated by ``settings.manage``; the user-membership routes
are gated by ``users.manage``. Mirrors ``test_admin_tax`` (mocked auth + client).
"""
from unittest.mock import patch
from uuid import uuid4

from tests.fixtures.access import (
    make_user_no_permissions,
    make_user_with_permissions,
)


def _auth_headers():
    return {"Authorization": "Bearer valid"}


def _mock_auth(mock_repo_cls, mock_auth_cls, user):
    mock_repo_cls.return_value.find_by_id.return_value = user
    mock_auth_cls.return_value.verify_token.return_value = str(uuid4())


def _slug(prefix: str = "grp") -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


class TestUserGroupPermissions:
    def test_list_unauthenticated(self, client):
        assert client.get("/api/v1/admin/user-groups").status_code == 401

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_forbidden_without_permission(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        _mock_auth(mock_repo_cls, mock_auth_cls, make_user_no_permissions())
        response = client.get("/api/v1/admin/user-groups", headers=_auth_headers())
        assert response.status_code == 403

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_allowed_with_permission(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.get("/api/v1/admin/user-groups", headers=_auth_headers())
        assert response.status_code == 200
        assert "groups" in response.get_json()


class TestUserGroupCrud:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_create_and_get(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        slug = _slug("vip")
        create = client.post(
            "/api/v1/admin/user-groups",
            json={"slug": slug, "name": "VIP", "lang": "en"},
            headers=_auth_headers(),
        )
        assert create.status_code == 201
        group_id = create.get_json()["group"]["id"]

        fetched = client.get(
            f"/api/v1/admin/user-groups/{group_id}", headers=_auth_headers()
        )
        assert fetched.status_code == 200
        assert fetched.get_json()["group"]["slug"] == slug

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_duplicate_slug_rejected(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        slug = _slug("dup")
        client.post(
            "/api/v1/admin/user-groups",
            json={"slug": slug, "name": "One"},
            headers=_auth_headers(),
        )
        response = client.post(
            "/api/v1/admin/user-groups",
            json={"slug": slug, "name": "Two"},
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_parent_group_must_exist(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        response = client.post(
            "/api/v1/admin/user-groups",
            json={"slug": _slug("child"), "name": "Child", "parent_group": "ghost"},
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_update_and_delete(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        group_id = client.post(
            "/api/v1/admin/user-groups",
            json={"slug": _slug("ed"), "name": "Old"},
            headers=_auth_headers(),
        ).get_json()["group"]["id"]

        update = client.put(
            f"/api/v1/admin/user-groups/{group_id}",
            json={"name": "New"},
            headers=_auth_headers(),
        )
        assert update.status_code == 200
        assert update.get_json()["group"]["name"] == "New"

        delete = client.delete(
            f"/api/v1/admin/user-groups/{group_id}", headers=_auth_headers()
        )
        assert delete.status_code == 200
        assert (
            client.get(
                f"/api/v1/admin/user-groups/{group_id}", headers=_auth_headers()
            ).status_code
            == 404
        )

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_bulk_delete(self, mock_repo_cls, mock_auth_cls, client):
        _mock_auth(
            mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
        )
        ids = []
        for _ in range(2):
            ids.append(
                client.post(
                    "/api/v1/admin/user-groups",
                    json={"slug": _slug("bulk"), "name": "B"},
                    headers=_auth_headers(),
                ).get_json()["group"]["id"]
            )
        response = client.post(
            "/api/v1/admin/user-groups/bulk-delete",
            json={"ids": ids},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert response.get_json()["deleted"] == 2


class TestUserMembershipRoutes:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_and_set_groups(self, mock_repo_cls, mock_auth_cls, client):
        from vbwd.extensions import db
        from vbwd.models.user import User

        user = make_user_with_permissions("settings.manage", "users.manage")
        _mock_auth(mock_repo_cls, mock_auth_cls, user)

        slug = _slug("member")
        client.post(
            "/api/v1/admin/user-groups",
            json={"slug": slug, "name": "Member"},
            headers=_auth_headers(),
        )

        target = User(email=f"s73-route-{uuid4().hex}@example.com", password_hash="x")
        db.session.add(target)
        db.session.commit()

        empty = client.get(
            f"/api/v1/admin/users/{target.id}/groups", headers=_auth_headers()
        )
        assert empty.status_code == 200
        assert empty.get_json()["group_slugs"] == []

        put = client.put(
            f"/api/v1/admin/users/{target.id}/groups",
            json={"group_slugs": [slug]},
            headers=_auth_headers(),
        )
        assert put.status_code == 200
        assert put.get_json()["group_slugs"] == [slug]
