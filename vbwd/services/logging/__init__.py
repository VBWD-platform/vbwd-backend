"""Unified logging layer (Sprint 58.5, D9) — one router + one event subscriber.

Built on the ``logs`` namespace of the FilesystemManager (Sprint 58.0). A single
:class:`VbwdLogRouter` (a ``logging.Handler`` on the root logger) routes every
Python log record to ``logs/<scope>/<stream>.log`` by deriving the *scope* from
the logger name and the *stream* from the level; an :class:`EventLogSubscriber`
mirrors every EventBus publish to ``logs/core/events.log`` (the global audit) —
the stream whose absence hid the contact-form failure.

Both write JSON-lines through the manager (never their own ``open()``), so they
inherit confinement, the append policy, permissions, and the single var-root,
and both apply a :func:`redact` pass so secrets never reach disk (Security #6).
"""
from .config import LoggingConfig, parse_log_level
from .redaction import redact
from .router import VbwdLogRouter
from .subscriber import EventLogSubscriber

__all__ = [
    "LoggingConfig",
    "parse_log_level",
    "VbwdLogRouter",
    "EventLogSubscriber",
    "redact",
]
