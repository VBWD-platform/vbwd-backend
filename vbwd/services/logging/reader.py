"""``LogReaderService`` — the centralized read side of the unified logging layer
(Sprint 106, S106.0).

The write path (Sprint 58.5) scatters JSON-lines across
``logs/<scope>/<stream>.log`` plus size-rotated ``.1 … .N`` segments. This
service is the inverse: given the same ``logs`` namespace of the
FilesystemManager it **parses, merges, time-orders, and filters** those records
back into a single newest-first view — so an operator (who, in production, has
only SFTP access to the box) can answer "what errored in the last 15 minutes,
across everything?" through one admin API.

It is **scope-agnostic**: it discovers whatever scope directories exist under
``logs/`` and never names a plugin — so it satisfies the core-agnosticism
oracle exactly like the router and the FilesystemManager it builds on.

Reads are **capped** (``max_lines_per_request`` / ``max_bytes_scanned``, tunable
via ``var/core/logging.json``) and walk newest segment → oldest only until a cap
is hit; whatever is dropped is surfaced on :class:`LogQueryResult`
(``truncated`` / ``bytes_scanned``), never silently. Malformed lines are skipped
and counted, never fatal.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

LOGS_NAMESPACE = "logs"

# Canonical stream order (error first) used when presenting the discovered set.
STREAM_ORDER = ("error", "warnings", "info", "events")

# A stream file is ``<stream>.log`` (active) or ``<stream>.log.<N>`` (rotated).
_STREAM_FILE_RE = re.compile(r"^(?P<stream>[A-Za-z0-9_-]+)\.log(?:\.(?P<index>\d+))?$")

# A scope name is a single safe path segment (no separators, no traversal).
_SCOPE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Python level names -> numeric value, for the ``min_level`` floor. Records with
# no ``level`` (the events audit trail) are never dropped by a level floor.
_LEVEL_VALUE: Dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
_LEVEL_NAME_TO_VALUE = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def parse_min_level(value: Optional[str]) -> Optional[int]:
    """Map a level-name query param to a numeric floor, or ``None`` for "all"."""
    if value is None:
        return None
    return _LEVEL_NAME_TO_VALUE.get(str(value).strip().lower())


def encode_cursor(before_ts: float) -> str:
    """Opaque "records strictly older than this ts" pagination pointer."""
    raw = json.dumps({"before_ts": before_ts}).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: Optional[str]) -> Optional[float]:
    """Decode a cursor back to its ``before_ts`` float; ``None`` on junk/empty."""
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        value = json.loads(raw).get("before_ts")
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class LogReaderConfig:
    """Read caps — code defaults; ops override via ``var/core/logging.json``."""

    max_lines_per_request: int = 1000
    max_bytes_scanned: int = 25 * 1024 * 1024
    default_window_minutes: int = 60
    tail_backfill_lines: int = 50


@dataclass
class LogQueryResult:
    """One page of merged records + the facts a caller needs to keep paging."""

    records: List[Dict[str, Any]] = field(default_factory=list)
    next_cursor: Optional[str] = None
    truncated: bool = False
    bytes_scanned: int = 0
    segments_scanned: int = 0
    malformed_skipped: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "records": self.records,
            "next_cursor": self.next_cursor,
            "truncated": self.truncated,
            "bytes_scanned": self.bytes_scanned,
            "segments_scanned": self.segments_scanned,
            "malformed_skipped": self.malformed_skipped,
        }


class LogReaderService:
    """Read, merge, and filter the on-disk JSON-lines logs (scope-agnostic)."""

    def __init__(
        self, filesystem_manager: Any, config: Optional[LogReaderConfig] = None
    ) -> None:
        self._filesystem_manager = filesystem_manager
        self._config = config or LogReaderConfig()

    @property
    def config(self) -> LogReaderConfig:
        return self._config

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_scopes(self) -> Dict[str, List[str]]:
        """Return ``{"scopes": [...], "streams": [...]}`` actually present."""
        scopes: List[str] = []
        streams: set[str] = set()
        for entry in sorted(self._filesystem_manager.listdir(LOGS_NAMESPACE, "")):
            if entry.endswith(".lock"):
                continue
            entry_streams = self._streams_in_scope(entry)
            if entry_streams:
                scopes.append(entry)
                streams.update(entry_streams)
        ordered_streams = [name for name in STREAM_ORDER if name in streams]
        ordered_streams += sorted(streams - set(STREAM_ORDER))
        return {"scopes": scopes, "streams": ordered_streams}

    def _streams_in_scope(self, scope: str) -> set[str]:
        found: set[str] = set()
        for name in self._safe_listdir(scope):
            match = _STREAM_FILE_RE.match(name)
            if match:
                found.add(match.group("stream"))
        return found

    def _safe_listdir(self, scope: str) -> List[str]:
        try:
            return self._filesystem_manager.listdir(LOGS_NAMESPACE, scope)
        except ValueError:
            return []

    def _segments(self, scope: str, stream: str) -> List[str]:
        """Relative segment paths for ``scope/stream``, NEWEST first.

        Active ``stream.log`` is the newest, then ``stream.log.1`` (next newest)
        through the highest ``.N`` (oldest).
        """
        active: Optional[str] = None
        rotated: List[tuple[int, str]] = []
        for name in self._safe_listdir(scope):
            match = _STREAM_FILE_RE.match(name)
            if not match or match.group("stream") != stream:
                continue
            index = match.group("index")
            if index is None:
                active = name
            else:
                rotated.append((int(index), name))
        ordered: List[str] = []
        if active is not None:
            ordered.append(f"{scope}/{active}")
        for _, name in sorted(rotated):
            ordered.append(f"{scope}/{name}")
        return ordered

    # ------------------------------------------------------------------
    # Validation (route maps ValueError -> 400)
    # ------------------------------------------------------------------

    def _known_scopes(self) -> List[str]:
        return self.list_scopes()["scopes"]

    def _validate_scopes(self, scopes: Optional[List[str]]) -> List[str]:
        known = self._known_scopes()
        if not scopes:
            return known
        unknown = [scope for scope in scopes if scope not in known]
        if unknown:
            raise ValueError(f"Unknown log scope(s): {unknown}")
        return list(scopes)

    def _validate_streams(self, streams: Optional[List[str]]) -> List[str]:
        if not streams:
            return list(STREAM_ORDER)
        unknown = [s for s in streams if not _STREAM_FILE_RE.match(f"{s}.log")]
        if unknown:
            raise ValueError(f"Invalid log stream(s): {unknown}")
        return list(streams)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        *,
        scopes: Optional[List[str]] = None,
        streams: Optional[List[str]] = None,
        min_level: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        contains: Optional[str] = None,
        limit: Optional[int] = None,
        before_ts: Optional[float] = None,
    ) -> LogQueryResult:
        """Return one newest-first page of merged, filtered records."""
        selected_scopes = self._validate_scopes(scopes)
        selected_streams = self._validate_streams(streams)
        level_floor = parse_min_level(min_level)
        needle = contains.lower() if contains else None
        page_size = self._clamp_limit(limit)

        result = LogQueryResult()
        collected: List[Dict[str, Any]] = []
        bytes_budget = self._config.max_bytes_scanned

        for scope in selected_scopes:
            for stream in selected_streams:
                for segment in self._segments(scope, stream):
                    if result.bytes_scanned >= bytes_budget:
                        result.truncated = True
                        break
                    text = self._read_text(segment)
                    if text is None:
                        continue
                    result.bytes_scanned += len(text)
                    result.segments_scanned += 1
                    stop_stream = self._scan_segment(
                        text=text,
                        scope=scope,
                        stream=stream,
                        level_floor=level_floor,
                        since=since,
                        until=until,
                        needle=needle,
                        before_ts=before_ts,
                        collected=collected,
                        result=result,
                    )
                    if stop_stream:
                        break
                if result.bytes_scanned >= bytes_budget:
                    result.truncated = True

        collected.sort(key=lambda record: record.get("ts") or 0.0, reverse=True)

        if len(collected) > page_size:
            page = collected[:page_size]
            result.truncated = True
            result.next_cursor = encode_cursor(float(page[-1].get("ts") or 0.0))
        else:
            page = collected
            if result.truncated and page:
                result.next_cursor = encode_cursor(float(page[-1].get("ts") or 0.0))
        result.records = page
        return result

    def _scan_segment(
        self,
        *,
        text: str,
        scope: str,
        stream: str,
        level_floor: Optional[int],
        since: Optional[float],
        until: Optional[float],
        needle: Optional[str],
        before_ts: Optional[float],
        collected: List[Dict[str, Any]],
        result: LogQueryResult,
    ) -> bool:
        """Scan one segment newest-line-first. Returns True to stop this stream
        (the ``since`` lower bound was crossed — older segments are all older)."""
        for line in reversed(text.splitlines()):
            if not line.strip():
                continue
            record = self._parse_line(line)
            if record is None:
                result.malformed_skipped += 1
                continue
            record["scope"] = scope
            record["stream"] = stream
            timestamp = record.get("ts")
            if before_ts is not None and not (
                isinstance(timestamp, (int, float)) and timestamp < before_ts
            ):
                continue
            if (
                until is not None
                and isinstance(timestamp, (int, float))
                and (timestamp > until)
            ):
                continue
            if (
                since is not None
                and isinstance(timestamp, (int, float))
                and (timestamp < since)
            ):
                return True
            if not self._passes_level(record, level_floor):
                continue
            if needle is not None and needle not in line.lower():
                continue
            collected.append(record)
        return False

    @staticmethod
    def _passes_level(record: Dict[str, Any], level_floor: Optional[int]) -> bool:
        if level_floor is None:
            return True
        value = _LEVEL_VALUE.get(str(record.get("level", "")).upper())
        # Level-less records (events audit) are never dropped by a level floor.
        if value is None:
            return True
        return value >= level_floor

    def _clamp_limit(self, limit: Optional[int]) -> int:
        ceiling = self._config.max_lines_per_request
        if not limit or limit <= 0:
            return ceiling
        return min(int(limit), ceiling)

    @staticmethod
    def _parse_line(line: str) -> Optional[Dict[str, Any]]:
        try:
            parsed = json.loads(line)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _read_text(self, relative_path: str) -> Optional[str]:
        try:
            return self._filesystem_manager.read_text(LOGS_NAMESPACE, relative_path)
        except (FileNotFoundError, ValueError, OSError):
            return None

    # ------------------------------------------------------------------
    # Download (chronological raw ndjson)
    # ------------------------------------------------------------------

    def read_stream_raw(
        self, scope: str, stream: str, max_bytes: Optional[int] = None
    ) -> str:
        """Return a single ``scope/stream`` as chronological ndjson, byte-capped.

        Reads newest segments first up to the cap, then re-orders to chronological
        (oldest → newest) so the download reads naturally top-to-bottom.
        """
        self._validate_scopes([scope])
        self._validate_streams([stream])
        cap = (
            max_bytes
            if max_bytes and max_bytes > 0
            else (self._config.max_bytes_scanned)
        )
        collected_lines: List[str] = []
        scanned = 0
        for segment in self._segments(scope, stream):
            if scanned >= cap:
                break
            text = self._read_text(segment)
            if text is None:
                continue
            scanned += len(text)
            collected_lines.extend(ln for ln in text.splitlines() if ln.strip())
        # Segments are walked active (newest) → oldest; re-sort by ts to
        # guarantee chronological output regardless of segment boundaries.
        parsed = []
        for line in collected_lines:
            record = self._parse_line(line)
            ts = record.get("ts") if isinstance(record, dict) else None
            parsed.append((ts if isinstance(ts, (int, float)) else 0.0, line))
        parsed.sort(key=lambda pair: pair[0])
        return "\n".join(line for _, line in parsed)

    # ------------------------------------------------------------------
    # Live tail
    # ------------------------------------------------------------------

    def make_tail_cursor(
        self,
        scope: str,
        stream: str,
        *,
        min_level: Optional[str] = None,
        contains: Optional[str] = None,
        backfill: Optional[int] = None,
    ) -> "LogTailCursor":
        """Build a stateful tail cursor over one ``scope/stream`` (validated).

        Unlike query/download, the scope need not already exist on disk — you may
        tail a stream before its first line is written — so only the *name shape*
        is validated (defeating traversal), not its presence.
        """
        if not _SCOPE_NAME_RE.match(scope):
            raise ValueError(f"Invalid log scope name: {scope!r}")
        self._validate_streams([stream])
        return LogTailCursor(
            reader=self,
            scope=scope,
            stream=stream,
            min_level=parse_min_level(min_level),
            contains=contains.lower() if contains else None,
            backfill=(
                backfill if backfill is not None else self._config.tail_backfill_lines
            ),
        )

    def _active_segment(self, scope: str, stream: str) -> str:
        return f"{scope}/{stream}.log"


class LogTailCursor:
    """Stateful "give me the new lines since last poll" over the active file.

    Reads the active ``scope/stream.log`` each :meth:`poll`, tracking how many
    lines it has already emitted. On the first poll it backfills the last
    ``backfill`` lines so a freshly opened stream is not blank; afterwards it
    yields only appended lines. A shrink (the file rotated away) resets the
    counter so the new active file is read from the top — lines that rotated out
    between two polls are not re-emitted (documented, acceptable for a tail).
    """

    def __init__(
        self,
        *,
        reader: LogReaderService,
        scope: str,
        stream: str,
        min_level: Optional[int],
        contains: Optional[str],
        backfill: int,
    ) -> None:
        self._reader = reader
        self._scope = scope
        self._stream = stream
        self._min_level = min_level
        self._contains = contains
        self._backfill = max(0, backfill)
        self._emitted_lines = 0
        self._initialised = False

    def poll(self) -> List[Dict[str, Any]]:
        relative_path = self._reader._active_segment(self._scope, self._stream)
        text = self._reader._read_text(relative_path)
        lines = [ln for ln in (text or "").splitlines() if ln.strip()]

        if not self._initialised:
            self._initialised = True
            start = max(0, len(lines) - self._backfill)
            self._emitted_lines = len(lines)
            new_lines = lines[start:]
        elif len(lines) < self._emitted_lines:
            # Rotation happened: treat the whole new active file as fresh.
            self._emitted_lines = len(lines)
            new_lines = lines
        else:
            new_lines = lines[self._emitted_lines :]
            self._emitted_lines = len(lines)

        records: List[Dict[str, Any]] = []
        for line in new_lines:
            record = self._reader._parse_line(line)
            if record is None:
                continue
            record["scope"] = self._scope
            record["stream"] = self._stream
            if not self._reader._passes_level(record, self._min_level):
                continue
            if self._contains is not None and self._contains not in line.lower():
                continue
            records.append(record)
        return records
