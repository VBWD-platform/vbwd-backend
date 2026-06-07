"""DataExchangeRegistry — the DI singleton plugins register exchangers into.

Same pattern as ``line_item_registry`` / ``deletion_dependency_registry``:
a module-level singleton, populated at plugin enable-time, read by the generic
routes / CLI / permission catalog. Core registers no real exchanger here at
boot — S46.1 (core exchangers) and the plugins do.

``manifest_for(user)`` produces the perm- and config-filtered, clustered list
the UI renders, with per-entity ``can_export`` / ``can_import`` /
``can_export_pii`` flags resolved from the user's grants (superadmin = all).
"""
from typing import Any, Dict, List, Optional

from vbwd.services.data_exchange.port import (
    CLUSTER_SETTINGS,
    EntityExchanger,
)

SUPERADMIN_ROLE = "SUPER_ADMIN"
SETTINGS_VIEW_PERMISSION = "settings.view"
SETTINGS_MANAGE_PERMISSION = "settings.manage"


def _is_superadmin(user: Any) -> bool:
    role = getattr(user, "role", None)
    return getattr(role, "value", None) == SUPERADMIN_ROLE


class DataExchangeRegistry:
    """Registry of entity exchangers keyed by ``entity_key``."""

    def __init__(self) -> None:
        self._exchangers: Dict[str, EntityExchanger] = {}

    def register(self, exchanger: EntityExchanger) -> None:
        """Register (or replace) an exchanger by its entity key."""
        self._exchangers[exchanger.entity_key] = exchanger

    def unregister(self, entity_key: str) -> None:
        """Remove an exchanger (plugin disable)."""
        self._exchangers.pop(entity_key, None)

    def clear(self) -> None:
        """Reset all exchangers (test teardown / plugin reload)."""
        self._exchangers.clear()

    def get(self, entity_key: str) -> Optional[EntityExchanger]:
        return self._exchangers.get(entity_key)

    def all(self) -> List[EntityExchanger]:
        return list(self._exchangers.values())

    def can_export(self, exchanger: EntityExchanger, user: Any) -> bool:
        if not exchanger.supports_export:
            return False
        if _is_superadmin(user):
            return True
        if exchanger.cluster == CLUSTER_SETTINGS:
            return user.has_permission(SETTINGS_VIEW_PERMISSION)
        return user.has_permission(exchanger.export_permission)

    def can_import(self, exchanger: EntityExchanger, user: Any) -> bool:
        if not exchanger.supports_import:
            return False
        if _is_superadmin(user):
            return True
        if exchanger.cluster == CLUSTER_SETTINGS:
            return user.has_permission(SETTINGS_MANAGE_PERMISSION)
        return user.has_permission(exchanger.import_permission)

    def can_export_pii(self, exchanger: EntityExchanger, user: Any) -> bool:
        if not exchanger.pii_fields:
            return False
        if _is_superadmin(user):
            return True
        if exchanger.cluster == CLUSTER_SETTINGS:
            return user.has_permission(SETTINGS_VIEW_PERMISSION)
        return user.has_permission(exchanger.pii_export_permission)

    def manifest_for(
        self,
        user: Any,
        *,
        enabled_entities: Optional[List[str]] = None,
    ) -> List[dict]:
        """Perm- and config-filtered, clustered manifest for ``user``.

        ``enabled_entities`` is the optional ``data_exchange.enabled_entities``
        allow-list (D10); ``None`` means all are enabled. An entity appears
        only when enabled AND the user may export or import it.
        """
        manifest: List[dict] = []
        for exchanger in self._exchangers.values():
            if enabled_entities is not None and (
                exchanger.entity_key not in enabled_entities
            ):
                continue
            can_export = self.can_export(exchanger, user)
            can_import = self.can_import(exchanger, user)
            if not (can_export or can_import):
                continue
            manifest.append(
                {
                    "entity_key": exchanger.entity_key,
                    "label": exchanger.label,
                    "cluster": exchanger.cluster,
                    "supported_formats": sorted(exchanger.supported_formats),
                    "supports_export": exchanger.supports_export,
                    "supports_import": exchanger.supports_import,
                    "can_export": can_export,
                    "can_import": can_import,
                    "can_export_pii": self.can_export_pii(exchanger, user),
                }
            )
        manifest.sort(key=lambda item: (item["cluster"], item["entity_key"]))
        return manifest


# Module-level singleton — plugins register at enable-time, routes read at runtime.
data_exchange_registry = DataExchangeRegistry()
