"""Admin log-read routes (core, scope-agnostic) — Sprint 106 (S106.1 / S106.2).

The centralized view over the on-disk JSON-lines logs the unified logging layer
(Sprint 58.5) already writes. In production the box is reachable only over SFTP,
so an operator cannot ``tail``/``grep`` a log; these endpoints give them a
merged, filtered, time-ordered view through the admin API instead.

Endpoints (all ``@require_auth`` + ``@require_permission("logs.read")``):

    GET /api/v1/admin/logs/scopes    -> {scopes, streams}     (filter UI feed)
    GET /api/v1/admin/logs           -> {records, next_cursor, ...}
    GET /api/v1/admin/logs/download  -> one scope/stream as ndjson
    GET /api/v1/admin/logs/stream    -> SSE live tail

Scope/stream are validated against the live directory listing inside the
reader, so an unknown / ``../`` value is a 400 (never a path escape). The read
caps live in ``var/core/logging.json`` (ops override; code defaults are the
fallback), per the ops-config rule.
"""
from __future__ import annotations

import json
import time
from typing import List, Optional

from flask import Blueprint, Response, current_app, jsonify, request

from vbwd.middleware.auth import require_auth, require_permission
from vbwd.services.filesystem import LocalFilesystemManager
from vbwd.services.logging.reader import (
    LogReaderConfig,
    LogReaderService,
    decode_cursor,
)

admin_logs_bp = Blueprint("admin_logs", __name__, url_prefix="/api/v1/admin/logs")

PERM_READ = "logs.read"

# Ops-tunable read caps live in the host-mounted var/core/logging.json; code
# defaults (LogReaderConfig) are the fallback. Per feedback_ops_config_in_var.
_CORE_NAMESPACE = "core"
_CONFIG_FILE = "logging.json"

# SSE tail cadence + how long a single connection lives before the client must
# reconnect (bounds worker hold-time; the fe re-opens the EventSource).
_TAIL_POLL_SECONDS = 1.0
_TAIL_MAX_SECONDS = 600


def _filesystem_manager() -> LocalFilesystemManager:
    """A manager bound to the current VBWD_VAR_DIR (built per request, cheap)."""
    return LocalFilesystemManager()


def _load_reader_config(manager: LocalFilesystemManager) -> LogReaderConfig:
    raw = manager.read_json(_CORE_NAMESPACE, _CONFIG_FILE, default={})
    if not isinstance(raw, dict):
        return LogReaderConfig()
    defaults = LogReaderConfig()
    return LogReaderConfig(
        max_lines_per_request=int(
            raw.get("max_lines_per_request", defaults.max_lines_per_request)
        ),
        max_bytes_scanned=int(raw.get("max_bytes_scanned", defaults.max_bytes_scanned)),
        default_window_minutes=int(
            raw.get("default_window_minutes", defaults.default_window_minutes)
        ),
        tail_backfill_lines=int(
            raw.get("tail_backfill_lines", defaults.tail_backfill_lines)
        ),
    )


def _build_reader() -> LogReaderService:
    manager = _filesystem_manager()
    return LogReaderService(manager, config=_load_reader_config(manager))


def _multi(param: str) -> Optional[List[str]]:
    """Collect a repeatable / comma-separated query param into a list."""
    values: List[str] = []
    for raw in request.args.getlist(param):
        values.extend(part.strip() for part in raw.split(",") if part.strip())
    return values or None


def _float_arg(name: str) -> Optional[float]:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _int_arg(name: str) -> Optional[int]:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _resolve_since(reader: LogReaderService) -> Optional[float]:
    """Lower time bound: explicit ``since`` epoch, a ``minutes`` window, or the
    configured default window. ``since=0`` means "no lower bound" (all history).
    """
    explicit = _float_arg("since")
    if explicit is not None:
        return explicit
    now = time.time()
    minutes = _int_arg("minutes")
    if minutes is not None and minutes > 0:
        return now - minutes * 60
    return now - reader.config.default_window_minutes * 60


@admin_logs_bp.route("/scopes", methods=["GET"])
@require_auth
@require_permission(PERM_READ)
def list_scopes():
    """Return the discovered scopes + streams (feeds the filter UI)."""
    return jsonify(_build_reader().list_scopes()), 200


@admin_logs_bp.route("", methods=["GET"])
@require_auth
@require_permission(PERM_READ)
def query_logs():
    """Return a newest-first page of merged, filtered records."""
    reader = _build_reader()
    try:
        result = reader.query(
            scopes=_multi("scope"),
            streams=_multi("stream"),
            min_level=request.args.get("level"),
            since=_resolve_since(reader),
            until=_float_arg("until"),
            contains=request.args.get("contains"),
            limit=_int_arg("limit"),
            before_ts=decode_cursor(request.args.get("cursor")),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(result.to_dict()), 200


@admin_logs_bp.route("/download", methods=["GET"])
@require_auth
@require_permission(PERM_READ)
def download_stream():
    """Return one ``scope/stream`` as chronological ndjson (capped)."""
    scope = request.args.get("scope")
    stream = request.args.get("stream")
    if not scope or not stream:
        return jsonify({"error": "scope and stream are required"}), 400
    reader = _build_reader()
    try:
        raw = reader.read_stream_raw(scope, stream)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    filename = f"{scope}-{stream}.ndjson"
    response = Response(raw, mimetype="application/x-ndjson")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@admin_logs_bp.route("/stream", methods=["GET"])
@require_auth
@require_permission(PERM_READ)
def stream_logs():
    """Server-Sent-Events live tail of one ``scope/stream``.

    ``X-Accel-Buffering: no`` + ``Cache-Control: no-cache`` keep nginx (and any
    intermediary) from buffering the event-stream — without it the tail only
    flushes on disconnect (see project_sse_proxy_buffering_root_cause). Under
    pytest the generator drains once and returns instead of looping forever.
    """
    scope = request.args.get("scope")
    stream = request.args.get("stream")
    if not scope or not stream:
        return jsonify({"error": "scope and stream are required"}), 400
    reader = _build_reader()
    try:
        cursor = reader.make_tail_cursor(
            scope,
            stream,
            min_level=request.args.get("level"),
            contains=request.args.get("contains"),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    testing = bool(current_app.config.get("TESTING"))

    def generate():
        yield ": connected\n\n"
        deadline = time.time() + _TAIL_MAX_SECONDS
        while True:
            for record in cursor.poll():
                yield f"data: {json.dumps(record, default=str)}\n\n"
            if testing or time.time() >= deadline:
                break
            yield ": ping\n\n"  # heartbeat keeps the connection warm
            time.sleep(_TAIL_POLL_SECONDS)

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response
