"""``EventLogSubscriber`` — mirrors every EventBus publish to the audit stream.

Subscribes to ALL events (via the bus's ``subscribe_all``) and appends one
redacted JSON line ``{"ts", "event", "payload"}`` to ``logs/core/events.log`` —
the complete global audit trail (the stream whose absence hid the contact-form
"event fired, nothing handled it" bug).

Per-plugin attribution (``logs/<plugin>/events.log``) is best-effort and only
done when the publish carries a *reliable* origin signal, because the EventBus
``publish(name, payload)`` exposes no publisher identity. The two clean signals:
  * a namespaced event name ``plugins.<id>.…`` -> ``<id>``;
  * an explicit ``_origin`` / ``origin_plugin`` key in the payload.
No stack-walking is attempted; an un-attributable event stays core-only.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from .redaction import redact

logger = logging.getLogger(__name__)

LOGS_NAMESPACE = "logs"
EVENTS_STREAM = "events.log"
CORE_SCOPE = "core"
PLUGIN_EVENT_PREFIX = "plugins."
ORIGIN_KEYS = ("_origin", "origin_plugin")


def attribute_event(event_name: str, payload: Any) -> Optional[str]:
    """Return the originating plugin id for an event, or ``None`` if unknown."""
    if event_name.startswith(PLUGIN_EVENT_PREFIX):
        remainder = event_name[len(PLUGIN_EVENT_PREFIX) :]
        plugin_id = remainder.split(".", 1)[0]
        if plugin_id:
            return plugin_id
    if isinstance(payload, dict):
        for origin_key in ORIGIN_KEYS:
            origin = payload.get(origin_key)
            if isinstance(origin, str) and origin:
                return origin
    return None


class EventLogSubscriber:
    """Appends every EventBus publish to the audit log(s)."""

    def __init__(self, filesystem_manager: Any) -> None:
        self._filesystem_manager = filesystem_manager

    def register(self, bus: Any) -> None:
        """Subscribe to all events on *bus* so every publish is audited."""
        bus.subscribe_all(self._on_event)

    def _on_event(self, event_name: str, payload: Any) -> None:
        # Auditing must never crash a publish path; the bus already swallows
        # subscriber exceptions, but stay defensive here too.
        try:
            line = self._build_line(event_name, payload)
            self._append(f"{CORE_SCOPE}/{EVENTS_STREAM}", line)
            origin = attribute_event(event_name, payload)
            if origin and origin != CORE_SCOPE:
                self._append(f"{origin}/{EVENTS_STREAM}", line)
        except Exception:  # noqa: BLE001 — event audit must never propagate
            logger.debug("[event-audit] failed to write %s", event_name)

    def _build_line(self, event_name: str, payload: Any) -> str:
        record = {
            "ts": time.time(),
            "event": event_name,
            "payload": redact(payload),
        }
        return json.dumps(record, ensure_ascii=False, default=str) + "\n"

    def _append(self, relative_path: str, line: str) -> None:
        self._filesystem_manager.append_text(LOGS_NAMESPACE, relative_path, line)
