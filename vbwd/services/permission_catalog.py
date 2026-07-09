"""Shared permission-catalog collectors.

Single source of truth for the permission catalogs, consumed by both the
``/admin/access/*`` routes and the RBAC seeder (DRY). Two catalogs:

* **admin** (``collect_permission_catalog``) = core ``CORE_PERMISSIONS`` + each
  enabled plugin's ``admin_permissions`` + the derived data-exchange perms.
* **user** (``collect_user_permission_catalog``) = core ``CORE_USER_PERMISSIONS``
  + each enabled plugin's ``user_permissions`` (the fe-user / access-level
  permissions, e.g. ``user.profile.view``).

Core stays agnostic: plugin permissions are read through the injected (or
``current_app``) ``plugin_manager`` — never by importing a plugin module.
"""
from typing import Any, Optional


def _resolve_plugin_manager(plugin_manager: Optional[Any]) -> Optional[Any]:
    """Return the injected manager, else the active app's, else ``None``.

    Degrades to ``None`` (core-only) when called with no manager outside a
    Flask app context, so a collector never raises for its caller.
    """
    if plugin_manager is not None:
        return plugin_manager
    try:
        from flask import current_app

        return getattr(current_app, "plugin_manager", None)
    except RuntimeError:
        # No application context — no resolvable manager (core-only).
        return None


def _collect_plugin_permissions(manager: Optional[Any], attribute: str) -> dict:
    """Map each enabled plugin's non-empty ``attribute`` list by plugin name."""
    collected: dict = {}
    if manager is not None:
        for plugin in manager.get_enabled_plugins():
            permissions = getattr(plugin, attribute, None)
            if permissions:
                collected[plugin.metadata.name] = permissions
    return collected


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

    manager = _resolve_plugin_manager(plugin_manager)
    catalog.update(_collect_plugin_permissions(manager, "admin_permissions"))

    data_exchange_permissions = _collect_data_exchange_permissions()
    if data_exchange_permissions:
        catalog["data_exchange"] = data_exchange_permissions

    return catalog


def collect_user_permission_catalog(*, plugin_manager: Optional[Any] = None) -> dict:
    """Collect the user-facing permission catalog from core + enabled plugins.

    Mirror of :func:`collect_permission_catalog` for USER (System C / access-
    level) permissions: core = ``CORE_USER_PERMISSIONS``, each enabled plugin
    contributes its ``user_permissions`` (e.g. subscription declares
    ``user.profile.view``). Consumed by the RBAC seeder (so the default access
    levels' grants resolve) and the ``/admin/access/user-permissions`` route.

    Returns:
        Mapping of source name -> list of permission entries. The ``"core"``
        key is always present.
    """
    from vbwd.routes.admin.access import CORE_USER_PERMISSIONS

    catalog = {"core": CORE_USER_PERMISSIONS}

    manager = _resolve_plugin_manager(plugin_manager)
    catalog.update(_collect_plugin_permissions(manager, "user_permissions"))

    return catalog


def _collect_data_exchange_permissions() -> list:
    """Derive sales-cluster export/import/PII perms from the exchange registry.

    Settings-cluster exchangers reuse the existing ``settings.view`` /
    ``settings.manage`` permissions, so they contribute nothing here. Computed
    dynamically from whatever is registered (DRY single source).
    """
    from vbwd.services.data_exchange.port import CLUSTER_SALES
    from vbwd.services.data_exchange.registry import data_exchange_registry

    permissions: list = []
    for exchanger in data_exchange_registry.all():
        if exchanger.cluster != CLUSTER_SALES:
            continue
        group = f"Data Exchange — {exchanger.cluster.capitalize()}"
        if exchanger.supports_export:
            permissions.append(
                {
                    "key": exchanger.export_permission,
                    "label": f"Export {exchanger.label}",
                    "group": group,
                }
            )
        if exchanger.supports_import:
            permissions.append(
                {
                    "key": exchanger.import_permission,
                    "label": f"Import {exchanger.label}",
                    "group": group,
                }
            )
        if exchanger.pii_fields:
            permissions.append(
                {
                    "key": exchanger.pii_export_permission,
                    "label": f"Export {exchanger.label} (PII)",
                    "group": group,
                }
            )
    return permissions
