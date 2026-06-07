"""Unit tests for the VBWD envelope: JSON build/validate, CSV, ZIP bundle."""
import io
import zipfile

import pytest

from vbwd.services.data_exchange.envelope import (
    ENVELOPE_VERSION,
    BundleEntry,
    EnvelopeError,
    build_bundle,
    build_envelope,
    read_bundle,
    rows_from_csv,
    rows_to_csv,
    validate_envelope,
)


# ── JSON envelope ────────────────────────────────────────────────────────


def test_build_envelope_shape():
    envelope = build_envelope(
        "widgets", [{"code": "a"}], instance="main", export_format="json"
    )
    assert envelope["vbwd_export"] == "widgets"
    assert envelope["version"] == ENVELOPE_VERSION
    assert envelope["instance"] == "main"
    assert envelope["format"] == "json"
    assert envelope["widgets"] == [{"code": "a"}]
    assert "exported_at" in envelope


def test_validate_envelope_returns_rows():
    envelope = build_envelope("widgets", [{"code": "a"}], instance="main")
    rows = validate_envelope(envelope, "widgets")
    assert rows == [{"code": "a"}]


def test_validate_rejects_wrong_export_kind():
    envelope = build_envelope("widgets", [], instance="main")
    with pytest.raises(EnvelopeError):
        validate_envelope(envelope, "gadgets")


def test_validate_rejects_bad_version():
    envelope = build_envelope("widgets", [], instance="main")
    envelope["version"] = 999
    with pytest.raises(EnvelopeError):
        validate_envelope(envelope, "widgets")


def test_validate_rejects_non_dict_payload():
    with pytest.raises(EnvelopeError):
        validate_envelope([], "widgets")


def test_validate_rejects_missing_rows_list():
    with pytest.raises(EnvelopeError):
        validate_envelope(
            {"vbwd_export": "widgets", "version": ENVELOPE_VERSION}, "widgets"
        )


# ── CSV round-trip ───────────────────────────────────────────────────────


def test_csv_round_trip_flat_rows():
    rows = [
        {"code": "a", "label": "Alpha"},
        {"code": "b", "label": "Beta"},
    ]
    csv_text = rows_to_csv(rows)
    assert "code" in csv_text and "label" in csv_text
    parsed = rows_from_csv(csv_text)
    assert parsed == rows


def test_csv_empty_rows_yields_empty_string():
    assert rows_to_csv([]) == ""
    assert rows_from_csv("") == []


# ── ZIP bundle ───────────────────────────────────────────────────────────


def test_bundle_round_trip_with_asset_binary():
    entries = [
        BundleEntry(
            entity_key="widgets",
            export_format="json",
            content=build_envelope("widgets", [{"code": "a"}], instance="main"),
        )
    ]
    asset_bytes = b"\x89PNG-binary-blob"
    archive = build_bundle(entries, instance="main", assets={"logo.png": asset_bytes})

    manifest, read_entries, read_assets = read_bundle(archive)

    assert manifest["instance"] == "main"
    assert manifest["contents"][0]["entity_key"] == "widgets"
    assert manifest["contents"][0]["version"] == ENVELOPE_VERSION
    assert read_entries["widgets"]["widgets"] == [{"code": "a"}]
    assert read_assets["logo.png"] == asset_bytes


def test_read_bundle_rejects_path_traversal_asset():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json",
            '{"instance": "main", "version": 1, "contents": []}',
        )
        archive.writestr("../../etc/passwd", b"x")
    with pytest.raises(EnvelopeError):
        read_bundle(buffer.getvalue())


def test_read_bundle_rejects_zip_bomb_over_cap():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            '{"instance": "main", "version": 1, "contents": []}',
        )
        archive.writestr("assets/huge.bin", b"0" * (5 * 1024 * 1024))
    with pytest.raises(EnvelopeError):
        read_bundle(buffer.getvalue(), max_total_bytes=1024)
