"""S106.0 — acceptance tests for :class:`LogReaderService` (centralized read).

The reader is the scope-agnostic counterpart to the write-path router: it parses,
merges, time-orders, and filters the on-disk JSON-lines logs the router already
writes, across rotation segments and scopes. These tests drive it directly with a
``tmp_path``-rooted :class:`LocalFilesystemManager` — exactly like the router
acceptance tests — so no app boot or disk-router wiring is involved.

Covered behaviours (the sprint's TDD plan, S106.0):
  * ``list_scopes`` enumerates only real scope directories + the streams present;
  * ``query`` merges records newest-first across scopes and rotation segments;
  * filters: scope, stream, ``min_level``, ``since``/``until`` window, ``contains``;
  * caps from config (``max_lines_per_request`` / ``max_bytes_scanned``) and the
    cursor pagination they drive — truncation is surfaced, never silent;
  * malformed lines are skipped (counted), never fatal;
  * the events stream (level-less audit) is included and not dropped by a level
    floor;
  * scope/stream validation rejects unknown / traversal input (the route maps
    this to 400).
"""
import json

import pytest

from vbwd.services.filesystem import LocalFilesystemManager
from vbwd.services.logging.reader import (
    LogReaderConfig,
    LogReaderService,
    decode_cursor,
)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    var_root = tmp_path / "var"
    uploads_root = tmp_path / "uploads"
    var_root.mkdir()
    uploads_root.mkdir()
    monkeypatch.setenv("VBWD_VAR_DIR", str(var_root))
    monkeypatch.setenv("UPLOADS_BASE_PATH", str(uploads_root))
    monkeypatch.setenv("UPLOADS_BASE_URL", "/uploads")
    return LocalFilesystemManager()


def _write_lines(manager, relative_path, records):
    """Append JSON-line records (in chronological order) to a logs file."""
    for record in records:
        manager.append_text("logs", relative_path, json.dumps(record) + "\n")


def _record(ts, level, scope, msg, **extra):
    return {
        "ts": ts,
        "level": level,
        "scope": scope,
        "stream": {"ERROR": "error", "WARNING": "warnings", "INFO": "info"}[level],
        "logger": f"{scope}.logger",
        "msg": msg,
        **extra,
    }


# --------------------------------------------------------------------------
# list_scopes
# --------------------------------------------------------------------------


def test_list_scopes_enumerates_dirs_and_streams(manager):
    _write_lines(manager, "core/error.log", [_record(1.0, "ERROR", "core", "boom")])
    _write_lines(manager, "core/info.log", [_record(1.0, "INFO", "core", "hi")])
    _write_lines(
        manager,
        "bot_telegram/error.log",
        [_record(2.0, "ERROR", "bot_telegram", "poll failed")],
    )
    # A legacy top-level file is NOT a scope (it has no stream files under it).
    manager.append_text("logs", "core.log", "legacy\n")

    reader = LogReaderService(manager)
    result = reader.list_scopes()

    assert set(result["scopes"]) == {"core", "bot_telegram"}
    assert "error" in result["streams"]
    assert "info" in result["streams"]
    # Streams come back in the canonical order, error first.
    assert result["streams"].index("error") < result["streams"].index("info")


# --------------------------------------------------------------------------
# query — merge + ordering
# --------------------------------------------------------------------------


def test_query_merges_scopes_newest_first(manager):
    _write_lines(
        manager, "core/error.log", [_record(10.0, "ERROR", "core", "core-old")]
    )
    _write_lines(
        manager,
        "bot_telegram/error.log",
        [_record(20.0, "ERROR", "bot_telegram", "bot-new")],
    )

    reader = LogReaderService(manager)
    result = reader.query(since=0)

    assert [r["msg"] for r in result.records] == ["bot-new", "core-old"]


def test_query_reads_across_rotation_segments_in_time_order(manager):
    # error.log.1 is the OLDER segment; error.log is the active (newer) one.
    _write_lines(manager, "core/error.log.1", [_record(1.0, "ERROR", "core", "oldest")])
    _write_lines(
        manager,
        "core/error.log",
        [
            _record(2.0, "ERROR", "core", "middle"),
            _record(3.0, "ERROR", "core", "newest"),
        ],
    )

    reader = LogReaderService(manager)
    result = reader.query(since=0)

    assert [r["msg"] for r in result.records] == ["newest", "middle", "oldest"]


# --------------------------------------------------------------------------
# query — filters
# --------------------------------------------------------------------------


def test_query_filters_by_scope(manager):
    _write_lines(manager, "core/error.log", [_record(1.0, "ERROR", "core", "core")])
    _write_lines(manager, "shop/error.log", [_record(2.0, "ERROR", "shop", "shop")])

    reader = LogReaderService(manager)
    result = reader.query(scopes=["shop"], since=0)

    assert [r["scope"] for r in result.records] == ["shop"]


def test_query_filters_by_min_level(manager):
    _write_lines(
        manager,
        "core/info.log",
        [_record(1.0, "INFO", "core", "info-line")],
    )
    _write_lines(
        manager,
        "core/warnings.log",
        [_record(2.0, "WARNING", "core", "warn-line")],
    )
    _write_lines(
        manager,
        "core/error.log",
        [_record(3.0, "ERROR", "core", "error-line")],
    )

    reader = LogReaderService(manager)
    result = reader.query(min_level="warning", since=0)

    msgs = [r["msg"] for r in result.records]
    assert "info-line" not in msgs
    assert set(msgs) == {"warn-line", "error-line"}


def test_query_filters_by_time_window(manager):
    _write_lines(
        manager,
        "core/error.log",
        [
            _record(100.0, "ERROR", "core", "too-old"),
            _record(200.0, "ERROR", "core", "in-window"),
            _record(300.0, "ERROR", "core", "too-new"),
        ],
    )

    reader = LogReaderService(manager)
    result = reader.query(since=150.0, until=250.0)

    assert [r["msg"] for r in result.records] == ["in-window"]


def test_query_filters_by_contains_text(manager):
    _write_lines(
        manager,
        "core/error.log",
        [
            _record(1.0, "ERROR", "core", "database timeout"),
            _record(2.0, "ERROR", "core", "payment captured"),
        ],
    )

    reader = LogReaderService(manager)
    result = reader.query(contains="DATABASE", since=0)

    assert [r["msg"] for r in result.records] == ["database timeout"]


def test_query_includes_events_stream_regardless_of_level(manager):
    # events.log lines are the level-less audit trail.
    manager.append_text(
        "logs",
        "core/events.log",
        json.dumps({"ts": 5.0, "event": "payment.captured", "payload": {"x": 1}})
        + "\n",
    )

    reader = LogReaderService(manager)
    result = reader.query(streams=["events"], min_level="error", since=0)

    assert len(result.records) == 1
    assert result.records[0]["event"] == "payment.captured"
    # The reader injects scope/stream from the file location.
    assert result.records[0]["scope"] == "core"
    assert result.records[0]["stream"] == "events"


# --------------------------------------------------------------------------
# query — caps, pagination, malformed
# --------------------------------------------------------------------------


def test_query_respects_limit_and_returns_cursor(manager):
    _write_lines(
        manager,
        "core/error.log",
        [_record(float(i), "ERROR", "core", f"line-{i}") for i in range(1, 6)],
    )

    reader = LogReaderService(manager)
    result = reader.query(limit=2, since=0)

    assert [r["msg"] for r in result.records] == ["line-5", "line-4"]
    assert result.truncated is True
    assert result.next_cursor is not None
    # The cursor is the "before this ts" pointer for the next page.
    assert decode_cursor(result.next_cursor) == pytest.approx(4.0)

    page2 = reader.query(limit=2, since=0, before_ts=decode_cursor(result.next_cursor))
    assert [r["msg"] for r in page2.records] == ["line-3", "line-2"]


def test_query_skips_malformed_lines_and_counts_them(manager):
    manager.append_text("logs", "core/error.log", "{not valid json\n")
    _write_lines(manager, "core/error.log", [_record(2.0, "ERROR", "core", "good")])

    reader = LogReaderService(manager)
    result = reader.query(since=0)

    assert [r["msg"] for r in result.records] == ["good"]
    assert result.malformed_skipped == 1


def test_query_byte_cap_stops_mid_walk_and_marks_truncated(manager):
    # Three rotation segments; the byte cap is smaller than one segment, so the
    # newest→oldest walk stops after the first and never reads the older two.
    _write_lines(
        manager,
        "core/error.log",
        [_record(float(300 + i), "ERROR", "core", "x" * 200) for i in range(10)],
    )
    _write_lines(
        manager,
        "core/error.log.1",
        [_record(float(200 + i), "ERROR", "core", "older") for i in range(10)],
    )
    _write_lines(
        manager,
        "core/error.log.2",
        [_record(float(100 + i), "ERROR", "core", "oldest") for i in range(10)],
    )

    reader = LogReaderService(manager, config=LogReaderConfig(max_bytes_scanned=500))
    result = reader.query(since=0, limit=1000)

    assert result.truncated is True
    assert result.segments_scanned == 1  # only the active segment was read
    assert all(
        "older" not in r["msg"] and "oldest" not in r["msg"] for r in result.records
    )
    assert result.next_cursor is not None  # caller can keep paging into the gap


# --------------------------------------------------------------------------
# download + validation
# --------------------------------------------------------------------------


def test_read_stream_raw_returns_chronological_ndjson(manager):
    _write_lines(manager, "core/error.log.1", [_record(1.0, "ERROR", "core", "oldest")])
    _write_lines(manager, "core/error.log", [_record(2.0, "ERROR", "core", "newest")])

    reader = LogReaderService(manager)
    raw = reader.read_stream_raw("core", "error")

    lines = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert [r["msg"] for r in lines] == ["oldest", "newest"]


def test_unknown_scope_is_rejected(manager):
    _write_lines(manager, "core/error.log", [_record(1.0, "ERROR", "core", "x")])
    reader = LogReaderService(manager)

    with pytest.raises(ValueError):
        reader.query(scopes=["../etc"], since=0)
    with pytest.raises(ValueError):
        reader.read_stream_raw("does-not-exist", "error")


# --------------------------------------------------------------------------
# tail cursor
# --------------------------------------------------------------------------


def test_tail_cursor_emits_only_new_lines(manager):
    _write_lines(manager, "core/error.log", [_record(1.0, "ERROR", "core", "before")])

    reader = LogReaderService(manager)
    cursor = reader.make_tail_cursor("core", "error", backfill=10)

    first = cursor.poll()
    assert [r["msg"] for r in first] == ["before"]

    _write_lines(manager, "core/error.log", [_record(2.0, "ERROR", "core", "after")])
    second = cursor.poll()
    assert [r["msg"] for r in second] == ["after"]

    # No new appends -> nothing emitted.
    assert cursor.poll() == []


def test_tail_cursor_applies_level_filter(manager):
    reader = LogReaderService(manager)
    cursor = reader.make_tail_cursor("core", "error", backfill=10, min_level="error")
    cursor.poll()

    _write_lines(manager, "core/error.log", [_record(2.0, "ERROR", "core", "boom")])
    manager.append_text(
        "logs",
        "core/error.log",
        json.dumps(_record(3.0, "INFO", "core", "noise")) + "\n",
    )
    emitted = cursor.poll()
    assert [r["msg"] for r in emitted] == ["boom"]
