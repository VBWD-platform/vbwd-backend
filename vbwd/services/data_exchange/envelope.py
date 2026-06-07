"""The VBWD-standard envelope: JSON build/validate, CSV, and ZIP bundle.

Single home (DRY) for the serialisation formats, generalised from
``vbwd.services.country_io``. Three shapes:

* **JSON envelope** — ``{vbwd_export, version, exported_at, instance, format,
  <entity_key>: [rows]}``; :func:`validate_envelope` rejects a wrong kind or
  unsupported version (mirrors ``import_countries``' validation style).
* **CSV** — flat header + rows for entities whose rows have no nested objects.
  CSV carries no envelope metadata; the entity comes from the upload context.
* **ZIP bundle** — ``manifest.json`` (contents + versions + instance) + one
  ``<entity>.json|csv`` per entity + an ``assets/`` dir for binaries. Reading
  enforces a zip-bomb cap and an ``assets/``-only path-traversal guard.
"""
import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

ENVELOPE_KEY = "vbwd_export"
ENVELOPE_VERSION = 1
MANIFEST_FILENAME = "manifest.json"
ASSETS_DIR = "assets/"

# Zip-bomb guard: cap the total uncompressed size read from a bundle.
DEFAULT_MAX_BUNDLE_BYTES = 50 * 1024 * 1024


class EnvelopeError(ValueError):
    """Raised when an envelope or bundle is malformed / unsafe."""


# ── JSON envelope ────────────────────────────────────────────────────────


def build_envelope(
    entity_key: str,
    rows: List[dict],
    *,
    instance: str,
    export_format: str = "json",
) -> dict:
    """Wrap rows in the VBWD-standard JSON envelope."""
    return {
        ENVELOPE_KEY: entity_key,
        "version": ENVELOPE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "instance": instance,
        "format": export_format,
        entity_key: list(rows),
    }


def validate_envelope(data: object, expected_key: str) -> List[dict]:
    """Validate an envelope and return its rows.

    Raises :class:`EnvelopeError` if the payload is not an object, names a
    different export kind, uses an unsupported version, or lacks a rows list.
    """
    if not isinstance(data, dict):
        raise EnvelopeError("payload must be a JSON object")

    kind = data.get(ENVELOPE_KEY)
    if kind is not None and kind != expected_key:
        raise EnvelopeError(
            f"unexpected export kind '{kind}', expected '{expected_key}'"
        )

    version = data.get("version")
    if version is not None and version != ENVELOPE_VERSION:
        raise EnvelopeError(
            f"unsupported envelope version '{version}', expected {ENVELOPE_VERSION}"
        )

    rows = data.get(expected_key)
    if not isinstance(rows, list):
        raise EnvelopeError(f"'{expected_key}' must be a list of rows")
    return rows


# ── CSV ──────────────────────────────────────────────────────────────────


def rows_to_csv(rows: List[dict]) -> str:
    """Serialise flat rows to CSV (header + one row each). Empty → ''."""
    if not rows:
        return ""
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def rows_from_csv(text: str) -> List[dict]:
    """Parse CSV text into flat row dicts. Empty text → ``[]``."""
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


# ── ZIP bundle ───────────────────────────────────────────────────────────


@dataclass
class BundleEntry:
    """One entity's file inside a bundle: its envelope (json) or CSV text."""

    entity_key: str
    export_format: str
    content: Union[dict, str]


@dataclass
class _BundleContent:
    """Internal record of what was read back from a bundle."""

    entries: Dict[str, dict] = field(default_factory=dict)
    assets: Dict[str, bytes] = field(default_factory=dict)


def build_bundle(
    entries: List[BundleEntry],
    *,
    instance: str,
    assets: Optional[Dict[str, bytes]] = None,
) -> bytes:
    """Build a ZIP bundle from per-entity entries + optional binary assets."""
    buffer = io.BytesIO()
    contents = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            extension = "csv" if entry.export_format == "csv" else "json"
            filename = f"{entry.entity_key}.{extension}"
            if extension == "json":
                payload = json.dumps(entry.content, default=str)
            else:
                payload = entry.content if isinstance(entry.content, str) else ""
            archive.writestr(filename, payload)
            contents.append(
                {
                    "entity_key": entry.entity_key,
                    "file": filename,
                    "format": entry.export_format,
                    "version": ENVELOPE_VERSION,
                }
            )
        for asset_name, asset_bytes in (assets or {}).items():
            archive.writestr(f"{ASSETS_DIR}{asset_name}", asset_bytes)
        manifest = {
            "instance": instance,
            "version": ENVELOPE_VERSION,
            "contents": contents,
        }
        archive.writestr(MANIFEST_FILENAME, json.dumps(manifest))
    return buffer.getvalue()


def read_bundle(
    archive_bytes: bytes,
    *,
    max_total_bytes: int = DEFAULT_MAX_BUNDLE_BYTES,
) -> Tuple[dict, Dict[str, dict], Dict[str, bytes]]:
    """Read a bundle → ``(manifest, {entity_key: envelope}, {asset: bytes})``.

    Guards: rejects total uncompressed size over ``max_total_bytes``
    (zip-bomb) and any asset path that escapes the ``assets/`` dir
    (path-traversal).
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise EnvelopeError(f"invalid ZIP bundle: {exc}") from exc

    total = sum(info.file_size for info in archive.infolist())
    if total > max_total_bytes:
        raise EnvelopeError(
            f"bundle too large: {total} bytes exceeds cap {max_total_bytes}"
        )

    manifest = _read_manifest(archive)
    by_filename = {item.get("file"): item for item in manifest.get("contents", [])}

    entries: Dict[str, dict] = {}
    assets: Dict[str, bytes] = {}
    for info in archive.infolist():
        name = info.filename
        _reject_traversal(name)
        if name == MANIFEST_FILENAME:
            continue
        if name.startswith(ASSETS_DIR):
            asset_name = _safe_asset_name(name)
            assets[asset_name] = archive.read(name)
            continue
        content_item = by_filename.get(name)
        if content_item is None:
            continue
        entity_key = content_item["entity_key"]
        if name.endswith(".json"):
            entries[entity_key] = json.loads(archive.read(name))
        else:
            rows = rows_from_csv(archive.read(name).decode("utf-8"))
            entries[entity_key] = build_envelope(entity_key, rows, instance="")
    return manifest, entries, assets


def _read_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        raw = archive.read(MANIFEST_FILENAME)
    except KeyError as exc:
        raise EnvelopeError("bundle is missing manifest.json") from exc
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EnvelopeError(f"malformed manifest.json: {exc}") from exc
    if not isinstance(manifest, dict):
        raise EnvelopeError("manifest.json must be a JSON object")
    return manifest


def _reject_traversal(name: str) -> None:
    """Reject any archive member whose path escapes the archive root."""
    if name.startswith("/") or ".." in name.split("/"):
        raise EnvelopeError(f"unsafe path in bundle: {name}")


def _safe_asset_name(name: str) -> str:
    """Return the asset's relative name (already traversal-checked)."""
    return name[len(ASSETS_DIR) :]
