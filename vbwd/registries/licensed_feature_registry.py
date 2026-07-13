"""Registry of licensable features declared by enabled plugins.

Mirrors ``permission_catalog`` / ``entity_type_registry``: core owns the
mechanism, the domain data arrives from plugins. Each enabled plugin declares
its ``licensed_features`` (default ``()``); this collector unions them via the
injected ``plugin_manager`` — core imports no plugin and names no feature.
"""
from typing import Any, List, Optional


def _resolve_plugin_manager(plugin_manager: Optional[Any]) -> Optional[Any]:
    """Return the injected manager, else the active app's, else ``None``."""
    if plugin_manager is not None:
        return plugin_manager
    try:
        from flask import current_app

        return getattr(current_app, "plugin_manager", None)
    except RuntimeError:
        return None


def collect_licensed_features(*, plugin_manager: Optional[Any] = None) -> List[str]:
    """Ordered, de-duplicated list of every enabled plugin's licensed features.

    Args:
        plugin_manager: Object exposing ``get_enabled_plugins()``. When ``None``
            the active Flask app's ``plugin_manager`` is used; when none is
            resolvable, an empty list is returned (core-only).
    """
    manager = _resolve_plugin_manager(plugin_manager)
    features: List[str] = []
    seen: set = set()
    if manager is not None:
        for plugin in manager.get_enabled_plugins():
            for feature in getattr(plugin, "licensed_features", ()) or ():
                if feature not in seen:
                    seen.add(feature)
                    features.append(feature)
    return features


def is_licensable_feature(
    feature: str, *, plugin_manager: Optional[Any] = None
) -> bool:
    """Whether ``feature`` is declared by any enabled plugin."""
    return feature in collect_licensed_features(plugin_manager=plugin_manager)
