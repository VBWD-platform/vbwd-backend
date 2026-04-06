"""Tests for admin plugin management routes."""
import json
from unittest.mock import patch, MagicMock
from uuid import uuid4
from vbwd.models.enums import UserRole
from vbwd.plugins.base import BasePlugin, PluginMetadata, PluginStatus
from vbwd.plugins.config_store import PluginConfigStore, PluginConfigEntry


class MockPlugin(BasePlugin):
    """Mock plugin for route tests."""

    def __init__(
        self, name="test-plugin", version="1.0.0", status=PluginStatus.INITIALIZED
    ):
        super().__init__()
        self._name = name
        self._version = version
        self._status = status

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=self._name,
            version=self._version,
            author="Test",
            description=f"Test plugin {self._name}",
        )


def _mock_admin_auth(mock_auth_user_repo_class, mock_auth_class):
    """Set up admin auth mocks."""
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


def _make_config_store(plugin_name="backend-demo-plugin", status="disabled"):
    """Create a mock config store with get_by_name returning a PluginConfigEntry."""
    mock_store = MagicMock(spec=PluginConfigStore)
    entry = PluginConfigEntry(plugin_name=plugin_name, status=status)
    mock_store.get_by_name.return_value = entry
    mock_store.get_config.return_value = {}
    return mock_store


class TestGetPluginDetail:
    """Tests for GET /api/v1/admin/plugins/<name>."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_returns_plugin_detail_with_config_schema(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        """GET /admin/plugins/<name> returns config schema and admin config."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        plugin = MockPlugin("backend-demo-plugin")
        plugin.initialize()
        app.plugin_manager._plugins["backend-demo-plugin"] = plugin

        # Mock schema_reader
        mock_reader = MagicMock()
        mock_reader.get_config_schema.return_value = {
            "greeting": {"type": "string", "default": "Hello!"}
        }
        mock_reader.get_admin_config.return_value = {
            "tabs": [{"id": "general", "label": "General", "fields": []}]
        }
        app.schema_reader = mock_reader

        # Mock config_store with enabled status
        mock_store = _make_config_store("backend-demo-plugin", "enabled")
        mock_store.get_config.return_value = {"greeting": "Custom Hello"}
        app.config_store = mock_store

        response = client.get(
            "/api/v1/admin/plugins/backend-demo-plugin",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "backend-demo-plugin"
        assert data["status"] == "active"
        assert data["configSchema"]["greeting"]["type"] == "string"
        assert data["adminConfig"]["tabs"][0]["id"] == "general"
        assert data["savedConfig"]["greeting"] == "Custom Hello"

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_returns_inactive_status_from_config_store(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        """GET /admin/plugins/<name> reads status from config_store, not in-memory."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        # Plugin is ENABLED in-memory, but disabled in config_store
        plugin = MockPlugin("backend-demo-plugin", status=PluginStatus.ENABLED)
        app.plugin_manager._plugins["backend-demo-plugin"] = plugin

        mock_store = _make_config_store("backend-demo-plugin", "disabled")
        app.config_store = mock_store

        response = client.get(
            "/api/v1/admin/plugins/backend-demo-plugin",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "inactive"

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_returns_404_for_unknown_plugin(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        """GET /admin/plugins/<name> returns 404 for unknown plugin."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        response = client.get(
            "/api/v1/admin/plugins/nonexistent",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 404


class TestPutPluginConfig:
    """Tests for PUT /api/v1/admin/plugins/<name>/config."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_saves_config_values(self, mock_repo_class, mock_auth_class, app, client):
        """PUT /admin/plugins/<name>/config saves config values."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        plugin = MockPlugin("backend-demo-plugin")
        plugin.initialize()
        app.plugin_manager._plugins["backend-demo-plugin"] = plugin

        mock_store = _make_config_store("backend-demo-plugin")
        app.config_store = mock_store

        response = client.put(
            "/api/v1/admin/plugins/backend-demo-plugin/config",
            data=json.dumps({"greeting": "Hello World"}),
            content_type="application/json",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["message"] == "Configuration saved"
        mock_store.save_config.assert_called_once_with(
            "backend-demo-plugin", {"greeting": "Hello World"}
        )

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_returns_404_for_unknown_plugin(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        """PUT /admin/plugins/<name>/config returns 404 for unknown plugin."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        response = client.put(
            "/api/v1/admin/plugins/nonexistent/config",
            data=json.dumps({"key": "value"}),
            content_type="application/json",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 404


class TestEnablePlugin:
    """Tests for POST /api/v1/admin/plugins/<name>/enable."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_enable_persists_to_config_store(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        """Enable writes to config_store (source of truth)."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        plugin = MockPlugin("backend-demo-plugin")
        plugin.initialize()
        app.plugin_manager._plugins["backend-demo-plugin"] = plugin

        mock_store = _make_config_store("backend-demo-plugin", "disabled")
        app.config_store = mock_store

        response = client.post(
            "/api/v1/admin/plugins/backend-demo-plugin/enable",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "enabled"
        mock_store.save.assert_called_once_with("backend-demo-plugin", "enabled", {})

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_enable_returns_404_for_unknown(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        """Enable returns 404 for unknown plugin."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        response = client.post(
            "/api/v1/admin/plugins/nonexistent/enable",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 404


class TestDisablePlugin:
    """Tests for POST /api/v1/admin/plugins/<name>/disable."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_disable_persists_to_config_store(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        """Disable writes to config_store (source of truth)."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        plugin = MockPlugin("backend-demo-plugin", status=PluginStatus.ENABLED)
        app.plugin_manager._plugins["backend-demo-plugin"] = plugin

        mock_store = _make_config_store("backend-demo-plugin", "enabled")
        app.config_store = mock_store

        response = client.post(
            "/api/v1/admin/plugins/backend-demo-plugin/disable",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "disabled"
        mock_store.save.assert_called_once_with("backend-demo-plugin", "disabled", {})

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_disable_does_not_400_from_initialized_state(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        """Disable succeeds even when in-memory state is INITIALIZED (multi-worker fix)."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        # Plugin in INITIALIZED state in this worker (not ENABLED)
        plugin = MockPlugin("backend-demo-plugin", status=PluginStatus.INITIALIZED)
        app.plugin_manager._plugins["backend-demo-plugin"] = plugin

        mock_store = _make_config_store("backend-demo-plugin", "enabled")
        app.config_store = mock_store

        response = client.post(
            "/api/v1/admin/plugins/backend-demo-plugin/disable",
            headers={"Authorization": "Bearer valid_token"},
        )

        # Must NOT return 400 — config_store is the source of truth
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "disabled"

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_disable_returns_404_for_unknown(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        """Disable returns 404 for unknown plugin."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        response = client.post(
            "/api/v1/admin/plugins/nonexistent/disable",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 404


class TestListPluginsHasConfig:
    """Tests for GET /api/v1/admin/plugins with hasConfig flag."""

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_includes_has_config_flag(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        """GET /admin/plugins includes hasConfig flag per plugin."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        plugin = MockPlugin("backend-demo-plugin")
        plugin.initialize()
        app.plugin_manager._plugins["backend-demo-plugin"] = plugin

        mock_reader = MagicMock()
        mock_reader.get_admin_config.return_value = {"tabs": [{"id": "general"}]}
        app.schema_reader = mock_reader

        # Config store for status reading
        mock_store = _make_config_store("backend-demo-plugin", "enabled")
        app.config_store = mock_store

        response = client.get(
            "/api/v1/admin/plugins",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.get_json()
        found = [p for p in data["plugins"] if p["name"] == "backend-demo-plugin"]
        assert len(found) == 1
        assert found[0]["hasConfig"] is True
        assert found[0]["status"] == "active"

    @patch("vbwd.middleware.auth.AuthService")
    @patch("vbwd.middleware.auth.UserRepository")
    def test_list_reads_status_from_config_store(
        self, mock_repo_class, mock_auth_class, app, client
    ):
        """GET /admin/plugins reads status from config_store, not in-memory."""
        _mock_admin_auth(mock_repo_class, mock_auth_class)

        # Plugin ENABLED in-memory but disabled in config_store
        plugin = MockPlugin("test-plugin", status=PluginStatus.ENABLED)
        app.plugin_manager._plugins["test-plugin"] = plugin

        mock_store = _make_config_store("test-plugin", "disabled")
        app.config_store = mock_store

        response = client.get(
            "/api/v1/admin/plugins",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.get_json()
        found = [p for p in data["plugins"] if p["name"] == "test-plugin"]
        assert len(found) == 1
        assert found[0]["status"] == "inactive"
