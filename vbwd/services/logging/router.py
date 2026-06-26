"""``VbwdLogRouter`` — the single root logging handler (Sprint 58.5, D9).

For each :class:`logging.LogRecord` it derives a *scope* from the logger name
(``plugins.<id>.…`` -> ``<id>``; ``vbwd.…`` / root / anything else -> ``core``)
and a *stream* from the level (ERROR/CRITICAL -> ``error``, WARNING ->
``warnings``, INFO -> ``info``; below INFO is dropped), folds a disallowed
(scope, stream) into the core file for that stream, then appends one redacted
JSON line via the FilesystemManager's ``logs`` namespace — with size-based
rotation. Emit is wrapped end-to-end so logging can never crash the app.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, Callable, Dict, Optional, Tuple

from .config import (
    CORE_SCOPE,
    STREAM_ERROR,
    STREAM_INFO,
    STREAM_WARNINGS,
    LoggingConfig,
)
from .redaction import redact

LOGS_NAMESPACE = "logs"
PLUGIN_LOGGER_PREFIX = "plugins."

# Fields that are standard on a LogRecord and therefore not "extra" context.
_STANDARD_RECORD_FIELDS = frozenset(vars(logging.makeLogRecord({})).keys())


def derive_scope(logger_name: str) -> str:
    """Return the scope for a logger name: a plugin id, or ``core``."""
    if logger_name and logger_name.startswith(PLUGIN_LOGGER_PREFIX):
        remainder = logger_name[len(PLUGIN_LOGGER_PREFIX) :]
        plugin_id = remainder.split(".", 1)[0]
        if plugin_id:
            return plugin_id
    return CORE_SCOPE


def derive_stream(level: int) -> Optional[str]:
    """Return the stream name for a level band, or ``None`` if below INFO."""
    if level >= logging.ERROR:
        return STREAM_ERROR
    if level >= logging.WARNING:
        return STREAM_WARNINGS
    if level >= logging.INFO:
        return STREAM_INFO
    return None


def _extract_extra(record: logging.LogRecord) -> Dict[str, Any]:
    """Return the user-supplied ``extra`` context attached to a record.

    Two shapes are supported: a single ``vbwd_extra`` dict (the convention this
    layer prefers) and any non-standard attributes set directly on the record.
    """
    extra: Dict[str, Any] = {}
    vbwd_extra = getattr(record, "vbwd_extra", None)
    if isinstance(vbwd_extra, dict):
        extra.update(vbwd_extra)
    for key, value in vars(record).items():
        if key in _STANDARD_RECORD_FIELDS or key == "vbwd_extra":
            continue
        extra[key] = value
    return extra


class VbwdLogRouter(logging.Handler):
    """Root ``logging.Handler`` routing records into the ``logs`` namespace."""

    def __init__(
        self,
        filesystem_manager: Any,
        config: Optional[LoggingConfig] = None,
        level: int = logging.INFO,
        ship_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        super().__init__(level=level)
        self._filesystem_manager = filesystem_manager
        self._config = config or LoggingConfig()
        # Optional Phase-2 ship-out hook: receives the redacted payload dict for
        # every written record. Decoupled (injected, not imported) so the router
        # stays testable and names no shipping machinery. Guarded at the call
        # site — a ship-hook failure never affects the disk write.
        self._ship_hook = ship_hook

    def _target(self, scope: str, stream: str) -> Tuple[str, str]:
        """Return the (json_scope, relative_path) for a (scope, stream).

        If *scope* is not allowed to write *stream*, the line is redirected to
        the ``core`` file for that stream, but the JSON scope stays the original
        so attribution survives the fold.
        """
        if stream in self._config.allowed_streams(scope):
            return scope, f"{scope}/{stream}.log"
        return scope, f"{CORE_SCOPE}/{stream}.log"

    def _build_payload(
        self, record: logging.LogRecord, scope: str, stream: str
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ts": time.time(),
            "level": record.levelname,
            "scope": scope,
            "stream": stream,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = _extract_extra(record)
        if extra:
            payload.update(redact(extra))
        return payload

    def _build_line(self, record: logging.LogRecord, scope: str, stream: str) -> str:
        return json.dumps(
            self._build_payload(record, scope, stream),
            ensure_ascii=False,
            default=str,
        )

    def emit(self, record: logging.LogRecord) -> None:
        # Logging must NEVER crash the app: the whole emit is guarded; on any
        # failure we fall back to stderr and never raise out of emit().
        payload: Optional[Dict[str, Any]] = None
        try:
            stream = derive_stream(record.levelno)
            if stream is None:
                return
            # S90 G2 — app-log verbosity floor. At ``warning`` the info stream
            # stops being written; at ``error`` info+warnings stop. Default
            # ``info`` keeps today's behaviour. (events.log is a separate path.)
            if record.levelno < self._config.min_level:
                return
            scope = derive_scope(record.name)
            json_scope, relative_path = self._target(scope, stream)
            payload = self._build_payload(record, json_scope, stream)
            line = json.dumps(payload, ensure_ascii=False, default=str)
            self._filesystem_manager.append_with_rotation(
                LOGS_NAMESPACE,
                relative_path,
                line + "\n",
                max_bytes=self._config.max_bytes,
                backups=self._config.backups,
            )
        except Exception:  # noqa: BLE001 — logging must never propagate
            self._fallback(record)
        # Phase 2 — fan the redacted payload to the ship-out hook, INDEPENDENTLY
        # of the disk write and fully guarded: a shipping failure must never
        # break logging. Only ships records that passed the floor + were built.
        if payload is not None and self._ship_hook is not None:
            try:
                self._ship_hook(payload)
            except Exception:  # noqa: BLE001 — shipping must never propagate
                pass

    @staticmethod
    def _fallback(record: logging.LogRecord) -> None:
        try:
            print(
                f"[vbwd-log-router fallback] {record.name} {record.levelname}: "
                f"{record.getMessage()}",
                file=sys.stderr,
            )
        except Exception:  # noqa: BLE001 — last resort, swallow everything
            pass
