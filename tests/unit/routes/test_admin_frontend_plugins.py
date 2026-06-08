"""Tests for admin frontend-plugin management routes.

The backend owns authoritative plugin state for every vbwd app — core
backend plugins (existing admin_plugins_bp) plus the frontend manifests
for fe-admin and fe-user. This set of routes exposes the per-app
manifests so the fe-admin UI can call a single backend endpoint to
enable/disable a frontend plugin and have it persisted on disk.
"""
import json
import os
import threading
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


class TestFrontendPluginsManagerRouting:
    """S58.1 — manifests are now written through the FilesystemManager's

    ``plugins`` namespace (INPLACE_LOCKED). Behaviour is identical: the same
    env-derived on-disk path, byte-identical JSON, the same API responses; the
    new guarantees are flock-guarded (no torn read) and inode preservation
    (no rename — the bind-mount contract).
    """

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_enable_preserves_byte_identical_serialization(
        self, mock_user_repo_class, mock_auth_class, client, tmp_path
    ):
        """The on-disk file is pretty JSON (indent=2) with a trailing newline,

        exactly as the hand-rolled writer produced it.
        """
        user_id = uuid4()
        _wire_auth(mock_user_repo_class, mock_auth_class, user_id)

        manifest_path = tmp_path / "fe-admin-plugins.json"
        _write_manifest(manifest_path, {"booking": False})

        with patch(
            "vbwd.routes.admin.frontend_plugins.MANIFEST_PATHS",
            {"admin": str(manifest_path)},
        ):
            client.post(
                "/api/v1/admin/frontend-plugins/admin/booking/enable",
                headers={"Authorization": "Bearer valid_token"},
            )

        raw = manifest_path.read_text()
        # Same serialization the original used: indent=2 + trailing newline.
        expected = (
            json.dumps(
                {"plugins": {"booking": {"enabled": True, "version": "1.0.0"}}},
                indent=2,
            )
            + "\n"
        )
        assert raw == expected

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_env_var_override_path_is_honoured(
        self, mock_user_repo_class, mock_auth_class, client, tmp_path, monkeypatch
    ):
        """Setting ``VBWD_FE_ADMIN_PLUGINS_JSON`` makes writes land there."""
        user_id = uuid4()
        _wire_auth(mock_user_repo_class, mock_auth_class, user_id)

        manifest_path = tmp_path / "custom-location" / "fe-admin-plugins.json"
        manifest_path.parent.mkdir(parents=True)
        _write_manifest(manifest_path, {"booking": False})

        monkeypatch.setenv("VBWD_FE_ADMIN_PLUGINS_JSON", str(manifest_path))
        # Re-resolve the env map the way the module does at import time.
        from vbwd.routes.admin import frontend_plugins as module

        with patch.object(module, "MANIFEST_PATHS", module._default_manifest_paths()):
            response = client.post(
                "/api/v1/admin/frontend-plugins/admin/booking/enable",
                headers={"Authorization": "Bearer valid_token"},
            )

        assert response.status_code == 200
        on_disk = json.loads(manifest_path.read_text())
        assert on_disk["plugins"]["booking"]["enabled"] is True

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_enable_preserves_inode_no_rename(
        self, mock_user_repo_class, mock_auth_class, client, tmp_path
    ):
        """INPLACE_LOCKED: the file is rewritten in place, never renamed."""
        user_id = uuid4()
        _wire_auth(mock_user_repo_class, mock_auth_class, user_id)

        manifest_path = tmp_path / "fe-admin-plugins.json"
        _write_manifest(manifest_path, {"booking": False})
        inode_before = os.stat(manifest_path).st_ino

        with patch(
            "vbwd.routes.admin.frontend_plugins.MANIFEST_PATHS",
            {"admin": str(manifest_path)},
        ):
            client.post(
                "/api/v1/admin/frontend-plugins/admin/booking/enable",
                headers={"Authorization": "Bearer valid_token"},
            )

        assert os.stat(manifest_path).st_ino == inode_before


class TestFrontendPluginsTornReadRace:
    """S58.1 headline regression test — the original bug.

    A reader container could see half-written JSON during a write because the
    writer used ``open(w)`` in place with NO lock. Routing through the
    ``plugins`` namespace (INPLACE_LOCKED, flock-guarded) eliminates this: a
    reader under a shared lock never observes a truncated/invalid manifest.
    """

    def test_concurrent_writer_reader_never_sees_torn_manifest(self, tmp_path):
        from vbwd.routes.admin.frontend_plugins import (
            _read_manifest,
            _write_manifest,
        )

        manifest_path = str(tmp_path / "fe-admin-plugins.json")
        big = {
            "plugins": {
                name: {"enabled": True, "version": "1.0.0"}
                for name in (f"plugin-{index}" for index in range(200))
            }
        }
        _write_manifest(manifest_path, big)

        stop = threading.Event()
        torn = []

        def writer():
            toggle = True
            while not stop.is_set():
                for plugin in big["plugins"].values():
                    plugin["enabled"] = toggle
                _write_manifest(manifest_path, big)
                toggle = not toggle

        def reader():
            while not stop.is_set():
                try:
                    manifest = _read_manifest(manifest_path)
                except (json.JSONDecodeError, ValueError):
                    torn.append("invalid-json")
                    return
                if len(manifest.get("plugins", {})) != 200:
                    torn.append("truncated")
                    return

        writer_thread = threading.Thread(target=writer)
        reader_thread = threading.Thread(target=reader)
        writer_thread.start()
        reader_thread.start()
        reader_thread.join(timeout=2.0)
        stop.set()
        writer_thread.join(timeout=2.0)
        reader_thread.join(timeout=2.0)

        assert torn == []
