"""JSON file-based plugin configuration store."""
import json
import logging
import os
import time
from typing import List, Optional

from vbwd.plugins.config_store import PluginConfigStore, PluginConfigEntry

logger = logging.getLogger(__name__)


class JsonFilePluginConfigStore(PluginConfigStore):
    """
    Persists plugin state to JSON files on disk.

    Uses two files:
      - plugins_dir/plugins.json  — plugin registry (name → {enabled, version, ...})
      - plugins_dir/config.json   — saved config values per plugin
    """

    def __init__(self, plugins_dir: str):
        self._plugins_dir = plugins_dir
        self._plugins_path = os.path.join(plugins_dir, "plugins.json")
        self._config_path = os.path.join(plugins_dir, "config.json")

    def _read_plugins(self) -> dict:
        """Read plugins.json, returning the 'plugins' dict."""
        return self._read_json(self._plugins_path).get("plugins", {})

    def _read_json(self, path: str) -> dict:
        """Read a JSON file, tolerating a transient mid-write truncation.

        A ``JSONDecodeError`` here almost always means another process (or a
        sibling app instance sharing a bind-mounted file) is mid-write.
        Returning ``{}`` on that window is catastrophic — ``get_enabled()``
        would report zero plugins and the whole boot silently de-registers
        every plugin. So we retry briefly before giving up; a genuinely absent
        file still returns ``{}`` immediately.
        """
        last_error: Optional[json.JSONDecodeError] = None
        for attempt in range(5):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except FileNotFoundError:
                return {}
            except json.JSONDecodeError as decode_error:
                last_error = decode_error
                time.sleep(0.01 * (attempt + 1))
        logger.warning(
            "Could not parse %s after retries (%s); treating as empty",
            path,
            last_error,
        )
        return {}

    def _write_plugins(self, plugins: dict) -> None:
        """Write plugins.json atomically so readers never see a truncated file.

        ``PluginManager._reconcile_version_pin`` re-stamps every enabled plugin
        on boot, so plugins.json is rewritten repeatedly while sibling app
        instances read the same bind-mounted file. A direct ``open(w)``
        truncates the file before re-filling it, and a reader catching that
        window gets a ``JSONDecodeError`` → zero enabled plugins. We write a
        sibling temp file and ``os.replace`` it (atomic on the same
        filesystem), falling back to an in-place write only when the path is a
        single-file bind mount that ``os.replace`` cannot swap.
        """
        self._write_json(self._plugins_path, {"plugins": plugins})

    def _read_config(self) -> dict:
        """Read config.json (same truncation tolerance as plugins)."""
        return self._read_json(self._config_path)

    def _write_config(self, config: dict) -> None:
        """Write config.json atomically (same constraints as plugins)."""
        self._write_json(self._config_path, config)

    def _write_json(self, path: str, data: dict) -> None:
        os.makedirs(self._plugins_dir, exist_ok=True)
        payload = json.dumps(data, indent=2)
        tmp_path = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp_path, "w") as f:
                f.write(payload)
            os.replace(tmp_path, path)
        except OSError:
            # Single-file bind mount: os.replace can't swap the inode
            # ("Device or resource busy"). Fall back to the in-place write the
            # original code used — still correct for the single-writer case.
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            with open(path, "w") as f:
                f.write(payload)

    def get_enabled(self) -> List[PluginConfigEntry]:
        """Get all enabled plugin config entries."""
        plugins = self._read_plugins()
        configs = self._read_config()
        result = []
        for name, info in plugins.items():
            if info.get("enabled"):
                result.append(
                    PluginConfigEntry(
                        plugin_name=name,
                        status="enabled",
                        config=configs.get(name, {}),
                        version=info.get("version"),
                    )
                )
        return result

    def save(
        self,
        plugin_name: str,
        status: str,
        config: Optional[dict] = None,
        version: Optional[str] = None,
    ) -> None:
        """Save plugin status, optional config, and an optional version stamp.

        When ``version`` is provided it is written as the manifest pin; when
        omitted, an existing pin is preserved (status-only updates do not touch
        the version).
        """
        plugins = self._read_plugins()

        if plugin_name not in plugins:
            plugins[plugin_name] = {
                "enabled": False,
                "version": version or "1.0.0",
                "installedAt": "",
                "source": "local",
            }
        elif version is not None:
            plugins[plugin_name]["version"] = version

        plugins[plugin_name]["enabled"] = status == "enabled"
        self._write_plugins(plugins)

        if config is not None:
            configs = self._read_config()
            configs[plugin_name] = config
            self._write_config(configs)

    def get_by_name(self, plugin_name: str) -> Optional[PluginConfigEntry]:
        """Get plugin config by name."""
        plugins = self._read_plugins()
        info = plugins.get(plugin_name)
        if not info:
            return None
        configs = self._read_config()
        return PluginConfigEntry(
            plugin_name=plugin_name,
            status="enabled" if info.get("enabled") else "disabled",
            config=configs.get(plugin_name, {}),
            version=info.get("version"),
        )

    def get_all(self) -> List[PluginConfigEntry]:
        """Get all plugin config entries."""
        plugins = self._read_plugins()
        configs = self._read_config()
        return [
            PluginConfigEntry(
                plugin_name=name,
                status="enabled" if info.get("enabled") else "disabled",
                config=configs.get(name, {}),
                version=info.get("version"),
            )
            for name, info in plugins.items()
        ]

    def get_config(self, plugin_name: str) -> dict:
        """Get saved config values for a plugin."""
        configs = self._read_config()
        return configs.get(plugin_name, {})

    def save_config(self, plugin_name: str, config: dict) -> None:
        """Save config values for a plugin."""
        configs = self._read_config()
        configs[plugin_name] = config
        self._write_config(configs)
