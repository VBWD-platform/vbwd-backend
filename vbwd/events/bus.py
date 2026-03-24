"""EventBus — lightweight pub/sub bus for plugin-to-plugin and core-to-plugin events.

Design:
- Plain dict of callback lists; no async, no persistence, no retry.
- Callbacks receive (event_name: str, data: dict) — plain data, no typed domain objects.
- Module-level singleton ``event_bus`` is the single instance used across the app.
- Thread-safe for read-heavy workloads (subscriptions set up at startup, never removed
  during a request in normal operation).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable, Dict, List

logger = logging.getLogger(__name__)

Callback = Callable[[str, dict], None]


class EventBus:
    """Pub/sub bus for plugin events.

    Plugins subscribe once in ``register_event_handlers(bus)`` and publish
    via ``event_bus.publish()``. No core file changes needed to add new events.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callback]] = defaultdict(list)
        self._global_subscribers: List[Callback] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe_all(self, callback: Callback) -> None:
        """Register *callback* to receive ALL published events.

        The callback receives ``(event_name: str, data: dict)`` for every
        event, regardless of event name.  Useful for plugins that need to
        react to any event dynamically (e.g. email plugin).
        """
        if callback not in self._global_subscribers:
            self._global_subscribers.append(callback)
            logger.debug("[bus] Global subscriber added: %s", callback)

    def subscribe(self, event_name: str, callback: Callback) -> None:
        """Register *callback* to be called when *event_name* is published.

        Args:
            event_name: Dot-separated event name (e.g. ``"subscription.activated"``).
            callback: Callable receiving ``(event_name: str, data: dict)``.
        """
        if callback not in self._subscribers[event_name]:
            self._subscribers[event_name].append(callback)
            logger.debug("[bus] Subscribed %s → %s", event_name, callback)

    def unsubscribe(self, event_name: str, callback: Callback) -> None:
        """Remove *callback* from *event_name* subscribers (no-op if not found).

        Args:
            event_name: Event name used in :meth:`subscribe`.
            callback: Previously registered callback.
        """
        try:
            self._subscribers[event_name].remove(callback)
            logger.debug("[bus] Unsubscribed %s → %s", event_name, callback)
        except ValueError:
            pass

    def publish(self, event_name: str, data: dict) -> None:
        """Call all subscribers registered for *event_name*.

        Exceptions raised by individual subscribers are logged at WARNING level
        and do not prevent remaining subscribers from being called.

        Args:
            event_name: Event name to publish.
            data: Plain dict of event payload.
        """
        callbacks = list(self._subscribers.get(event_name, []))
        callbacks.extend(self._global_subscribers)
        if not callbacks:
            logger.debug("[bus] No subscribers for %s", event_name)
            return
        for cb in callbacks:
            try:
                cb(event_name, data)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[bus] Subscriber %s raised %s for event %s: %s",
                    cb,
                    type(exc).__name__,
                    event_name,
                    exc,
                )

    def has_subscribers(self, event_name: str) -> bool:
        """Return True if at least one subscriber is registered for *event_name*.

        Also returns True if global subscribers exist (they receive all events).
        """
        return bool(self._subscribers.get(event_name)) or bool(self._global_subscribers)


# Module-level singleton — imported as ``from vbwd.events import event_bus``
event_bus = EventBus()
