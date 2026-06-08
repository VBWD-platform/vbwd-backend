"""Configuration for the unified logging layer (Sprint 58.5, D9).

Holds the tunable policy the router applies: the per-scope stream allowlist
(which ``<stream>.log`` files a given scope may write — anything else folds into
the core file for that stream), the minimum level captured, and the size-based
rotation limits. Defaults match the requested shape: ``core`` keeps
``{error, warnings, info}`` while each plugin keeps ``{error}`` only, so a
plugin's WARNING/INFO folds into the lean core streams.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set

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

    def allowed_streams(self, scope: str) -> Set[str]:
        """Return the stream set a *scope* is allowed to write to its own dir."""
        if scope in self.scope_streams:
            return self.scope_streams[scope]
        if scope == CORE_SCOPE:
            return self.default_core_streams
        return self.default_plugin_streams
