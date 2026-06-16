"""Configuration for the unified logging layer (Sprint 58.5, D9).

Holds the tunable policy the router applies: the per-scope stream allowlist
(which ``<stream>.log`` files a given scope may write — anything else folds into
the core file for that stream), the minimum level captured, and the size-based
rotation limits. Defaults match the requested shape: ``core`` keeps
``{error, warnings, info}`` while each plugin keeps ``{error}`` only, so a
plugin's WARNING/INFO folds into the lean core streams.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

CORE_SCOPE = "core"

# Stream file names per Python level band.
STREAM_ERROR = "error"
STREAM_WARNINGS = "warnings"
STREAM_INFO = "info"
STREAM_EVENTS = "events"

# Defaults — see module docstring.
DEFAULT_CORE_STREAMS: Set[str] = {STREAM_ERROR, STREAM_WARNINGS, STREAM_INFO}
DEFAULT_PLUGIN_STREAMS: Set[str] = {STREAM_ERROR}

# 10 MiB per file, 5 historical segments (error.log.1 … error.log.5).
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUPS = 5

# S90 G2 — app-log verbosity floor. ``info`` preserves today's behaviour
# (all of error/warnings/info written); prod opts down to ``warning`` so the
# ``info`` stream stops growing. The event stream (``events.log``) is written
# by the EventLogSubscriber, not this level band, so it is NEVER suppressed.
DEFAULT_MIN_LEVEL = logging.INFO
DEFAULT_LOG_LEVEL_NAME = "info"

_LEVEL_BY_NAME: Dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def parse_log_level(value: Optional[str], default: int = DEFAULT_MIN_LEVEL) -> int:
    """Map a ``VBWD_LOG_LEVEL`` string to a logging level int.

    Unknown / empty / ``None`` values fall back to *default* (``info``) so a
    typo can never crash the boot path or silence the app entirely.
    """
    if value is None:
        return default
    return _LEVEL_BY_NAME.get(str(value).strip().lower(), default)


@dataclass(frozen=True)
class LoggingConfig:
    """Tunable policy for :class:`VbwdLogRouter`.

    Attributes:
        scope_streams: per-scope override of the allowed stream set. A scope not
            present here uses :attr:`default_plugin_streams` (``core`` uses
            :attr:`default_core_streams`). A record whose (scope, stream) is not
            allowed is redirected to the ``core`` file for that stream.
        default_core_streams: streams the ``core`` scope may write.
        default_plugin_streams: streams any plugin scope may write.
        max_bytes: size threshold (bytes) at which a stream file is rotated.
        backups: number of historical ``.N`` segments to retain.
        min_level: app-log verbosity floor (S90 G2). A record below this level
            is dropped before it reaches a stream file. Default ``INFO``
            preserves the original behaviour; ``WARNING`` stops ``info.log``
            from growing. Does not affect the event stream.
    """

    scope_streams: Dict[str, Set[str]] = field(default_factory=dict)
    default_core_streams: Set[str] = field(
        default_factory=lambda: set(DEFAULT_CORE_STREAMS)
    )
    default_plugin_streams: Set[str] = field(
        default_factory=lambda: set(DEFAULT_PLUGIN_STREAMS)
    )
    max_bytes: int = DEFAULT_MAX_BYTES
    backups: int = DEFAULT_BACKUPS
    min_level: int = DEFAULT_MIN_LEVEL

    def allowed_streams(self, scope: str) -> Set[str]:
        """Return the stream set a *scope* is allowed to write to its own dir."""
        if scope in self.scope_streams:
            return self.scope_streams[scope]
        if scope == CORE_SCOPE:
            return self.default_core_streams
        return self.default_plugin_streams
