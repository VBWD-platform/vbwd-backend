"""Shared permission-catalog collector.

Single source of truth for the admin permission catalog, consumed by both
the ``/admin/access/permissions`` route and the RBAC seeder (DRY). The
catalog = core permissions + each enabled plugin's ``admin_permissions``.

Core stays agnostic: plugin permissions are read through the injected (or
``current_app``) ``plugin_manager`` — never by importing a plugin module.
"""
from typing import Any, Optional


def collect_permission_catalog(*, plugin_manager: Optional[Any] = None) -> dict:
    """Collect the admin permission catalog from core + enabled plugins.

    Args:
        plugin_manager: Object exposing ``get_enabled_plugins()``. When
            ``None`` the active Flask app's ``plugin_manager`` is used (so
            the route can call this with no argument). When no manager is
            resolvable, only the core permissions are returned.

    Returns:
        Mapping of source name -> list of permission entries. The ``"core"``
        key is always present. Each entry is the original dict
        (``{"key", "label", "group"}``); callers that only need keys read
        ``entry["key"]``.
    """
    from vbwd.routes.admin.access import CORE_PERMISSIONS

    catalog = {"core": CORE_PERMISSIONS}

    manager = plugin_manager
    if manager is None:
        from flask import current_app

        manager = getattr(current_app, "plugin_manager", None)

    if manager is not None:
        for plugin in manager.get_enabled_plugins():
            admin_permissions = getattr(plugin, "admin_permissions", None)
            if admin_permissions:
                catalog[plugin.metadata.name] = admin_permissions

    return catalog
