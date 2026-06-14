"""Registry of push-notification handlers (plugin-contributed, generic).

Core owns the push *mechanism* (device tokens + the APNs transport); plugins
own the *meaning* — translating their own domain objects into notification
payloads. A plugin registers a handler under its app key; when a plugin's
service emits a ``PushEvent``, ``dispatch`` calls every registered handler in
ascending ``priority`` order. With nothing registered, dispatch is a no-op —
the Liskov null-default (no push config = nothing breaks).

A handler exception is logged and never propagates: a push must NEVER fail
or block the operation that triggered it (e.g. a message send).

Mirrors ``vbwd/services/checkout_price_adjustment_registry.py`` (S36).
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Literal, Optional, Tuple

_module_logger = logging.getLogger(__name__)

DEFAULT_PRIORITY = 100


@dataclass
class PushEvent:
    """Something happened — maybe notify the recipient's devices.

    ``message`` and ``conversation`` are opaque plugin objects: core never
    reads them; only the registered handlers (plugin code) do.
    """

    message: Any
    conversation: Any
    recipient_user_id: Any
    app: str
    # S68 — ``"message"`` (default) is the S66 alert path; ``"badge_only"`` is
    # a silent badge-update push fired on read. ``originating_device_token``
    # lets a handler suppress the device that triggered the event (same-device
    # suppression). Both default for back-compat with existing callers.
    kind: Literal["message", "badge_only"] = "message"
    originating_device_token: Optional[str] = None


PushHandler = Callable[[PushEvent], None]

_handlers: Dict[str, Tuple[PushHandler, int]] = {}


def register_push_handler(
    app: str, handler: PushHandler, priority: int = DEFAULT_PRIORITY
) -> None:
    """Register (or replace) a plugin's push handler under its app key."""
    _handlers[app] = (handler, priority)


def unregister_push_handler(app: str) -> None:
    """Remove a plugin's handler (plugin disable)."""
    _handlers.pop(app, None)


def clear_push_handlers() -> None:
    """Reset all handlers (test teardown)."""
    _handlers.clear()


def dispatch(event: PushEvent, logger: Optional[logging.Logger] = None) -> None:
    """Call every registered handler, ordered by ascending priority.

    One handler raising is logged (via the injected logger, defaulting to
    this module's) and does not break the remaining handlers.
    """
    log = logger or _module_logger
    ordered_handlers = sorted(_handlers.items(), key=lambda item: item[1][1])
    for app_key, (handler, _priority) in ordered_handlers:
        try:
            handler(event)
        except Exception as error:
            log.error("push handler %r failed: %s", app_key, error)
