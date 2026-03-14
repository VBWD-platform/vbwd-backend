"""Repository for plugin configuration persistence (DB-backed).

Deprecated: Use JsonFilePluginConfigStore for new deployments.
This repository is retained for backward compatibility with existing
PostgreSQL-based plugin state.
"""
from src.utils.datetime_utils import utcnow
from typing import Optional, List
from src.models.plugin_config import PluginConfig
from src.plugins.config_store import PluginConfigStore, PluginConfigEntry


class PluginConfigRepository(PluginConfigStore):
    """CRUD repository for PluginConfig entries (DB-backed)."""

    def __init__(self, session):
        self._session = session

    def get_by_name(self, plugin_name: str) -> Optional[PluginConfigEntry]:
        """Get plugin config by name."""
        row = (
            self._session.query(PluginConfig)
            .filter(PluginConfig.plugin_name == plugin_name)
            .first()
        )
        if not row:
            return None
        return PluginConfigEntry(
            plugin_name=row.plugin_name,
            status=row.status,
            config=row.config or {},
        )

    def get_all(self) -> List[PluginConfigEntry]:
        """Get all plugin configs."""
        rows = self._session.query(PluginConfig).all()
        return [
            PluginConfigEntry(
                plugin_name=r.plugin_name,
                status=r.status,
                config=r.config or {},
            )
            for r in rows
        ]

    def get_enabled(self) -> List[PluginConfigEntry]:
        """Get all enabled plugin configs."""
        rows = (
            self._session.query(PluginConfig)
            .filter(PluginConfig.status == "enabled")
            .all()
        )
        return [
            PluginConfigEntry(
                plugin_name=r.plugin_name,
                status=r.status,
                config=r.config or {},
            )
            for r in rows
        ]

    def save(
        self, plugin_name: str, status: str, config: Optional[dict] = None
    ) -> None:
        """Create or update plugin config entry."""
        existing = (
            self._session.query(PluginConfig)
            .filter(PluginConfig.plugin_name == plugin_name)
            .first()
        )
        now = utcnow()

        if existing:
            existing.status = status
            existing.updated_at = now
            if config is not None:
                existing.config = config
            if status == "enabled":
                existing.enabled_at = now
            elif status == "disabled":
                existing.disabled_at = now
            self._session.commit()
            return

        entry = PluginConfig(
            plugin_name=plugin_name,
            status=status,
            config=config or {},
            created_at=now,
            updated_at=now,
        )
        if status == "enabled":
            entry.enabled_at = now  # type: ignore[assignment]
        elif status == "disabled":
            entry.disabled_at = now  # type: ignore[assignment]

        self._session.add(entry)
        self._session.commit()

    def get_config(self, plugin_name: str) -> dict:
        """Get saved config values for a plugin."""
        entry = self.get_by_name(plugin_name)
        return entry.config if entry else {}

    def save_config(self, plugin_name: str, config: dict) -> None:
        """Save config values for a plugin."""
        existing = (
            self._session.query(PluginConfig)
            .filter(PluginConfig.plugin_name == plugin_name)
            .first()
        )
        now = utcnow()

        if existing:
            existing.config = config
            existing.updated_at = now
            self._session.commit()
        else:
            entry = PluginConfig(
                plugin_name=plugin_name,
                status="disabled",
                config=config,
                created_at=now,
                updated_at=now,
            )
            self._session.add(entry)
            self._session.commit()

    def delete(self, plugin_name: str) -> bool:
        """Delete plugin config by name."""
        existing = (
            self._session.query(PluginConfig)
            .filter(PluginConfig.plugin_name == plugin_name)
            .first()
        )
        if existing:
            self._session.delete(existing)
            self._session.commit()
            return True
        return False
