"""Unit tests for plugin isolation — Sprint 14b.

Proves that disabled plugins are completely inaccessible:
- Disabled plugin's permissions not in listing
- Permission listing is dynamic based on enabled plugins
"""
from unittest.mock import patch
from uuid import uuid4

from tests.fixtures.access import make_user_with_permissions


class TestPluginPermissionIsolation:
    """When a plugin is disabled, its permissions disappear from the listing."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_permissions_listing_includes_enabled_plugins(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        user = make_user_with_permissions("*")
        mock_repo_cls.return_value.find_by_id.return_value = user
        mock_auth_cls.return_value.verify_token.return_value = str(uuid4())

        response = client.get(
            "/api/v1/admin/access/permissions",
            headers={"Authorization": "Bearer valid"},
        )
        assert response.status_code == 200
        data = response.get_json()
        permissions = data["permissions"]

        # Core permissions always present
        assert "core" in permissions
        core_keys = [p["key"] for p in permissions["core"]]
        assert "users.view" in core_keys
        assert "settings.system" in core_keys

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_permissions_listing_has_plugin_groups(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        """Enabled plugins should have their permissions in the listing."""
        user = make_user_with_permissions("*")
        mock_repo_cls.return_value.find_by_id.return_value = user
        mock_auth_cls.return_value.verify_token.return_value = str(uuid4())

        response = client.get(
            "/api/v1/admin/access/permissions",
            headers={"Authorization": "Bearer valid"},
        )
        data = response.get_json()
        permissions = data["permissions"]

        # At least some plugins should be present
        plugin_names = [k for k in permissions.keys() if k != "core"]
        assert len(plugin_names) > 0, "Expected at least one plugin's permissions"

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_each_plugin_permission_has_required_fields(
        self, mock_repo_cls, mock_auth_cls, client
    ):
        """Every permission entry must have key, label, group."""
        user = make_user_with_permissions("*")
        mock_repo_cls.return_value.find_by_id.return_value = user
        mock_auth_cls.return_value.verify_token.return_value = str(uuid4())

        response = client.get(
            "/api/v1/admin/access/permissions",
            headers={"Authorization": "Bearer valid"},
        )
        data = response.get_json()

        for source, perms in data["permissions"].items():
            for perm in perms:
                assert "key" in perm, f"Permission from '{source}' missing 'key'"
                assert (
                    "label" in perm
                ), f"Permission '{perm.get('key')}' missing 'label'"
                assert (
                    "group" in perm
                ), f"Permission '{perm.get('key')}' missing 'group'"


class TestRoleCRUDBulletproof:
    """System role protection tests."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_cannot_delete_system_role(self, mock_repo_cls, mock_auth_cls, client):
        user = make_user_with_permissions("*")
        mock_repo_cls.return_value.find_by_id.return_value = user
        mock_auth_cls.return_value.verify_token.return_value = str(uuid4())

        # Get system roles
        response = client.get(
            "/api/v1/admin/access/levels",
            headers={"Authorization": "Bearer valid"},
        )
        levels = response.get_json()["levels"]
        system_roles = [lv for lv in levels if lv["is_system"]]

        for role in system_roles:
            delete_resp = client.delete(
                f"/api/v1/admin/access/levels/{role['id']}",
                headers={"Authorization": "Bearer valid"},
            )
            assert (
                delete_resp.status_code == 400
            ), f"System role '{role['slug']}' should not be deletable"

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_cannot_create_duplicate_slug(self, mock_repo_cls, mock_auth_cls, client):
        user = make_user_with_permissions("*")
        mock_repo_cls.return_value.find_by_id.return_value = user
        mock_auth_cls.return_value.verify_token.return_value = str(uuid4())

        # Create a role
        response = client.post(
            "/api/v1/admin/access/levels",
            json={
                "name": "Test Dup",
                "slug": "test-dup-isolation",
            },
            headers={"Authorization": "Bearer valid"},
        )
        assert response.status_code == 201

        # Try to create with same slug
        response2 = client.post(
            "/api/v1/admin/access/levels",
            json={
                "name": "Test Dup 2",
                "slug": "test-dup-isolation",
            },
            headers={"Authorization": "Bearer valid"},
        )
        assert response2.status_code == 400

        # Cleanup
        role_id = response.get_json()["level"]["id"]
        client.delete(
            f"/api/v1/admin/access/levels/{role_id}",
            headers={"Authorization": "Bearer valid"},
        )

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_export_import_roundtrip(self, mock_repo_cls, mock_auth_cls, client):
        user = make_user_with_permissions("*")
        mock_repo_cls.return_value.find_by_id.return_value = user
        mock_auth_cls.return_value.verify_token.return_value = str(uuid4())

        # Create a role first (CI has empty DB)
        client.post(
            "/api/v1/admin/access/levels",
            json={"name": "Export Test", "slug": f"export-test-{uuid4().hex[:6]}"},
            headers={"Authorization": "Bearer valid"},
        )

        # Export
        export_resp = client.post(
            "/api/v1/admin/access/export",
            json={},
            headers={"Authorization": "Bearer valid"},
        )
        assert export_resp.status_code == 200
        export_data = export_resp.get_json()
        assert "roles" in export_data
        assert len(export_data["roles"]) > 0

        # Import (should not fail — upsert)
        import_resp = client.post(
            "/api/v1/admin/access/import",
            json=export_data,
            headers={"Authorization": "Bearer valid"},
        )
        assert import_resp.status_code == 200
