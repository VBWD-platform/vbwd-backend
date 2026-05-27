"""Plugin config schema reader — reads config.json and admin-config.json from plugin dirs."""
import json
import logging
import os
from typing import Dict, List

logger = logging.getLogger(__name__)


class PluginConfigSchemaReader:
    """
    Reads per-plugin config schema and admin config from plugin directories.

    Searches plugin directories for:
      - <plugin_dir>/config.json      — field definitions (type, default, description)
      - <plugin_dir>/admin-config.json — admin UI tab/field layout
    """

    def __init__(self, search_dirs: List[str]):
        self._search_dirs = search_dirs
        self._dir_map: Dict[str, str] = {}
        self._build_dir_map()

    def _build_dir_map(self) -> None:
        """Scan search dirs and map plugin names to their directory paths."""
        for search_dir in self._search_dirs:
            if not os.path.isdir(search_dir):
                continue
            for entry in os.listdir(search_dir):
                full_path = os.path.join(search_dir, entry)
                if not os.path.isdir(full_path):
                    continue
                # Read plugin name from __init__.py metadata or infer from directory
                # Map directory name to path
                self._dir_map[entry] = full_path

    def _find_plugin_dir(self, plugin_name: str) -> str | None:
        """Find the directory for a plugin by name.

        Tries exact match first, then scans for directories
        that might match (e.g. 'demoplugin' for 'backend-demo-plugin').
        """
        # Exact match
        if plugin_name in self._dir_map:
            return self._dir_map[plugin_name]

        # Normalized match (strip dashes/underscores)
        normalized = plugin_name.replace("-", "").replace("_", "").lower()
        for dir_name, dir_path in self._dir_map.items():
            if dir_name.replace("-", "").replace("_", "").lower() == normalized:
                return dir_path

        # Scan for __init__.py with matching plugin name
        for dir_name, dir_path in self._dir_map.items():
            init_path = os.path.join(dir_path, "__init__.py")
            if os.path.exists(init_path):
                try:
                    with open(init_path, "r") as file_handle:
                        content = file_handle.read()
                    if f'name="{plugin_name}"' in content:
                        return dir_path
                except OSError:
                    # S24 — narrow exception: skip unreadable __init__.py
                    # (permission denied, broken symlink, etc.); don't swallow
                    # programming errors.
                    continue

        return None

    def get_config_schema(self, plugin_name: str) -> dict:
        """Get the config schema (config.json) for a plugin."""
        plugin_dir = self._find_plugin_dir(plugin_name)
        if not plugin_dir:
            return {}

        config_path = os.path.join(plugin_dir, "config.json")
        if not os.path.exists(config_path):
            return {}

        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read config schema for '{plugin_name}': {e}")
            return {}

    def get_admin_config(self, plugin_name: str) -> dict:
        """Get the admin config (admin-config.json) for a plugin."""
        plugin_dir = self._find_plugin_dir(plugin_name)
        if not plugin_dir:
            return {}

        config_path = os.path.join(plugin_dir, "admin-config.json")
        if not os.path.exists(config_path):
            return {}

        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read admin config for '{plugin_name}': {e}")
            return {}
