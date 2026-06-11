"""Shared API-scope registry collector (S52).

Single source of truth for the API-key scope catalogue, consumed by the
scope endpoints and the key-management UIs (DRY). The catalogue = core
scopes (always empty — core ships **zero** domain scopes) + each enabled
plugin's declared ``api_scopes``.

Core stays agnostic: plugin scopes are read through the injected (or
``current_app``) ``plugin_manager`` — never by importing a plugin module.
Mirrors ``vbwd/services/permission_catalog.py`` verbatim.
"""
from typing import Any, Optional

# Core declares no API scopes — only plugins are gnostic about scope meaning.
CORE_API_SCOPES: list = []


def collect_api_scopes(
    *, plugin_manager: Optional[Any] = None, _resolve_app: bool = True
) -> dict:
    """Collect the API-scope catalogue from core + enabled plugins.

    Args:
        plugin_manager: Object exposing ``get_enabled_plugins()``. When
            ``None`` the active Flask app's ``plugin_manager`` is used (so a
            route can call this with no argument). When no manager is
            resolvable, only the (empty) core scopes are returned.
        _resolve_app: When False, the ``current_app`` fallback is skipped
            (used by unit tests that run outside an app context).

    Returns:
        Mapping of source name -> list of scope entries. ``"core"`` is always
        present (empty). Each plugin entry is a list of dicts with keys
        ``key``, ``label``, ``description``, ``user_grantable``.
    """
    catalog: dict = {"core": list(CORE_API_SCOPES)}

    manager = plugin_manager
    if manager is None and _resolve_app:
        from flask import current_app

        manager = getattr(current_app, "plugin_manager", None)

    if manager is not None:
        for plugin in manager.get_enabled_plugins():
            api_scopes = getattr(plugin, "api_scopes", None)
            if api_scopes:
                catalog[plugin.metadata.name] = api_scopes

    return catalog


def collect_user_grantable_scopes(*, plugin_manager: Optional[Any] = None) -> dict:
    """Same shape as ``collect_api_scopes`` but only ``user_grantable`` scopes.

    Used by the user self-service scopes endpoint — a user may only grant
    scopes a plugin marked self-grantable; admins may grant any registered
    scope.
    """
    full = collect_api_scopes(plugin_manager=plugin_manager)
    grantable: dict = {"core": list(CORE_API_SCOPES)}
    for source, scopes in full.items():
        if source == "core":
            continue
        allowed = [scope for scope in scopes if scope.get("user_grantable")]
        if allowed:
            grantable[source] = allowed
    return grantable
