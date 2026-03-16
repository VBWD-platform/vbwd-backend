"""EventContextRegistry — open-registry for email event template schemas.

Any plugin can register its own event type schemas here in ``on_enable()``
without editing the core email plugin files.

Usage from a plugin::

    from plugins.email.src.services.event_context_registry import EventContextRegistry

    class MyPlugin(BasePlugin):
        def on_enable(self):
            EventContextRegistry.register("my.event_happened", {
                "description": "Triggered when thing happens",
                "variables": {
                    "user_email": {"type": "string", "example": "user@example.com",
                                   "description": "Recipient"},
                    "thing_name": {"type": "string", "example": "Widget",
                                   "description": "Name of thing"},
                }
            })

The email admin routes read from this registry via :meth:`get_all` / :meth:`get`
instead of reading ``EVENT_CONTEXTS`` directly.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

_registry: Dict[str, Dict[str, Any]] = {}


def register(event_type: str, schema: Dict[str, Any]) -> None:
    """Register *schema* for *event_type*.

    Calling this more than once for the same *event_type* updates the entry
    (last-write wins), which allows plugins to override core defaults.

    Args:
        event_type: Dot-separated event name (e.g. ``"subscription.activated"``).
        schema: Dict with keys ``"description"`` (str) and ``"variables"``
            (dict of var_name → {type, description, example}).
    """
    if event_type in _registry:
        logger.debug("[EventContextRegistry] Updating schema for %s", event_type)
    else:
        logger.debug("[EventContextRegistry] Registering schema for %s", event_type)
    _registry[event_type] = schema


def get_all() -> List[Dict[str, Any]]:
    """Return all registered event type schemas as a list, sorted by key."""
    return [{"event_type": k, **v} for k, v in sorted(_registry.items())]


def get(event_type: str) -> Optional[Dict[str, Any]]:
    """Return the schema for *event_type*, or ``None`` if not registered."""
    return _registry.get(event_type)


def clear() -> None:
    """Remove all entries. Intended for use in tests only."""
    _registry.clear()
