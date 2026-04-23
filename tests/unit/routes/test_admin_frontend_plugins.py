"""Tests for admin frontend-plugin management routes.

The backend owns authoritative plugin state for every vbwd app — core
backend plugins (existing admin_plugins_bp) plus the frontend manifests
for fe-admin and fe-user. This set of routes exposes the per-app
manifests so the fe-admin UI can call a single backend endpoint to
enable/disable a frontend plugin and have it persisted on disk.
"""
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4


def _admin_user(user_id):
    user = MagicMock()
    user.status.value = "ACTIVE"
    user.id = user_id
    user.is_admin = True
    return user


def _wire_auth(mock_user_repo_class, mock_auth_class, user_id):
    mock_user_repo = MagicMock()
    mock_user_repo.find_by_id.return_value = _admin_user(user_id)
    mock_user_repo_class.return_value = mock_user_repo

    mock_auth = MagicMock()
    mock_auth.verify_token.return_value = str(user_id)
    mock_auth_class.return_value = mock_auth


def _write_manifest(path, plugins):
    path.write_text(
        json.dumps(
            {
                "plugins": {
                    name: {"enabled": enabled, "version": "1.0.0"}
                    for name, enabled in plugins.items()
                }
            },
            indent=2,
        )
    )


class TestFrontendPluginsManifest:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_manifest_returns_file_contents(
        self, mock_user_repo_class, mock_auth_class, client, tmp_path
    ):
        user_id = uuid4()
        _wire_auth(mock_user_repo_class, mock_auth_class, user_id)

        manifest_path = tmp_path / "fe-admin.json"
        _write_manifest(manifest_path, {"booking": True, "cms-admin": False})

        with patch(
            "vbwd.routes.admin.frontend_plugins.MANIFEST_PATHS",
            {"admin": str(manifest_path)},
        ):
            response = client.get(
                "/api/v1/admin/frontend-plugins/admin",
                headers={"Authorization": "Bearer valid_token"},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["plugins"]["booking"]["enabled"] is True
        assert data["plugins"]["cms-admin"]["enabled"] is False

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_get_manifest_returns_404_for_unknown_app(
        self, mock_user_repo_class, mock_auth_class, client
    ):
        user_id = uuid4()
        _wire_auth(mock_user_repo_class, mock_auth_class, user_id)

        with patch(
            "vbwd.routes.admin.frontend_plugins.MANIFEST_PATHS",
            {"admin": "/tmp/does-not-matter.json"},
        ):
            response = client.get(
                "/api/v1/admin/frontend-plugins/unknown-app",
                headers={"Authorization": "Bearer valid_token"},
            )
        assert response.status_code == 404

    def test_get_manifest_unauthenticated(self, client):
        response = client.get("/api/v1/admin/frontend-plugins/admin")
        assert response.status_code == 401


class TestFrontendPluginsEnable:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_enable_flips_the_flag_and_persists(
        self, mock_user_repo_class, mock_auth_class, client, tmp_path
    ):
        user_id = uuid4()
        _wire_auth(mock_user_repo_class, mock_auth_class, user_id)

        manifest_path = tmp_path / "fe-admin.json"
        _write_manifest(manifest_path, {"booking": False, "cms-admin": True})

        with patch(
            "vbwd.routes.admin.frontend_plugins.MANIFEST_PATHS",
            {"admin": str(manifest_path)},
        ):
            response = client.post(
                "/api/v1/admin/frontend-plugins/admin/booking/enable",
                headers={"Authorization": "Bearer valid_token"},
            )

        assert response.status_code == 200
        on_disk = json.loads(manifest_path.read_text())
        assert on_disk["plugins"]["booking"]["enabled"] is True
        # Other plugins untouched
        assert on_disk["plugins"]["cms-admin"]["enabled"] is True

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_enable_returns_404_when_plugin_missing_from_manifest(
        self, mock_user_repo_class, mock_auth_class, client, tmp_path
    ):
        user_id = uuid4()
        _wire_auth(mock_user_repo_class, mock_auth_class, user_id)

        manifest_path = tmp_path / "fe-admin.json"
        _write_manifest(manifest_path, {"cms-admin": True})

        with patch(
            "vbwd.routes.admin.frontend_plugins.MANIFEST_PATHS",
            {"admin": str(manifest_path)},
        ):
            response = client.post(
                "/api/v1/admin/frontend-plugins/admin/nonexistent/enable",
                headers={"Authorization": "Bearer valid_token"},
            )
        assert response.status_code == 404


class TestFrontendPluginsDisable:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_disable_flips_the_flag_and_persists(
        self, mock_user_repo_class, mock_auth_class, client, tmp_path
    ):
        user_id = uuid4()
        _wire_auth(mock_user_repo_class, mock_auth_class, user_id)

        manifest_path = tmp_path / "fe-admin.json"
        _write_manifest(manifest_path, {"booking": True, "cms-admin": True})

        with patch(
            "vbwd.routes.admin.frontend_plugins.MANIFEST_PATHS",
            {"admin": str(manifest_path)},
        ):
            response = client.post(
                "/api/v1/admin/frontend-plugins/admin/booking/disable",
                headers={"Authorization": "Bearer valid_token"},
            )

        assert response.status_code == 200
        on_disk = json.loads(manifest_path.read_text())
        assert on_disk["plugins"]["booking"]["enabled"] is False
        assert on_disk["plugins"]["cms-admin"]["enabled"] is True


class TestFrontendPluginsResponseShape:
    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_enable_response_includes_app_plugin_and_path(
        self, mock_user_repo_class, mock_auth_class, client, tmp_path
    ):
        user_id = uuid4()
        _wire_auth(mock_user_repo_class, mock_auth_class, user_id)

        manifest_path = tmp_path / "fe-admin-plugins.json"
        _write_manifest(manifest_path, {"booking": False})

        with patch(
            "vbwd.routes.admin.frontend_plugins.MANIFEST_PATHS",
            {"admin": str(manifest_path)},
        ):
            response = client.post(
                "/api/v1/admin/frontend-plugins/admin/booking/enable",
                headers={"Authorization": "Bearer valid_token"},
            )

        body = response.get_json()
        assert body == {
            "app": "admin",
            "plugin": "booking",
            "enabled": True,
            "updated_path": str(manifest_path),
        }
