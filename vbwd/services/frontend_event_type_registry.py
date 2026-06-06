"""Registry of allowed frontend event types (plugin-contributed).

Core's ``POST /api/v1/events`` accepts events forwarded from the frontend
EventBus, filtered by a security whitelist. Core owns only the **generic
platform** event types (``auth:*``, ``user:*``, ``payment:*``, ``plugin:*``);
plugins contribute their own domain event types (e.g. the subscription plugin
registers ``subscription:*``). This keeps core event-aware, not domain-aware:
core routes the whitelist check through this registry and never names a plugin
domain. With nothing registered, only the core base set is accepted — the
disabled-plugin path degrades gracefully (those events are simply rejected).
"""
from typing import Set

# Generic platform event types — these are core concerns (authentication,
# user lifecycle, payment, plugin lifecycle) that name no plugin domain.
_CORE_BASE_EVENT_TYPES: Set[str] = {
    # Auth events
    "auth:login",
    "auth:logout",
    "auth:token-refreshed",
    "auth:session-expired",
    # User events
    "user:registered",
    "user:updated",
    "user:deleted",
    # Payment events
    "payment:initiated",
    "payment:completed",
    "payment:failed",
    "payment:refunded",
    # Plugin events
    "plugin:registered",
    "plugin:initialized",
    "plugin:error",
    "plugin:stopped",
}

_plugin_event_types: Set[str] = set()


def register_frontend_event_types(types: Set[str]) -> None:
    """Add plugin-contributed frontend event types to the whitelist."""
    _plugin_event_types.update(types)


def unregister_frontend_event_types(types: Set[str]) -> None:
    """Remove plugin-contributed frontend event types (plugin disable)."""
    _plugin_event_types.difference_update(types)


def clear_frontend_event_types() -> None:
    """Reset all plugin-contributed types (test teardown / full disable)."""
    _plugin_event_types.clear()


def allowed_frontend_event_types() -> Set[str]:
    """Return the core base set plus every plugin-contributed type (a copy)."""
    return _CORE_BASE_EVENT_TYPES | _plugin_event_types
