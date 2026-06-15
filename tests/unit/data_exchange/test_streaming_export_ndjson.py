"""S89 Slice 1 — chunked export + NDJSON streaming on both ends.

Covers:
* :meth:`iter_export` yields rows in ``chunk_size`` batches and the
  concatenation equals the buffered ``export().rows`` (DRY / Liskov parity);
* the iterator pages the repository instead of ``.all()`` (streaming);
* NDJSON round-trip reproduces the rows byte-for-byte equal to the buffered
  JSON round-trip (parity across formats);
* a malformed NDJSON line is reported WITH its line number (never a silent skip);
* the NDJSON header line is required and validated against the entity.
"""
import json

import pytest

from vbwd.services.data_exchange.base_model_exchanger import BaseModelExchanger
from vbwd.services.data_exchange.envelope import (
    EnvelopeError,
    NDJSON_FORMAT,
    build_ndjson_header,
    iter_ndjson_lines,
    iter_ndjson_rows,
    validate_ndjson_header,
)
from vbwd.services.data_exchange.port import ExportSelector

from .fakes import FakeRecord, FakeRepository, FakeSession


def _make_exchanger(row_count=12):
    rows = [
        FakeRecord(f"code-{n}", f"Label {n}", f"secret-{n}", f"user-{n}@example.com")
        for n in range(row_count)
    ]
    repo = FakeRepository(rows)
    session = FakeSession()
    exchanger = BaseModelExchanger(
        entity_key="widgets",
        label="Widgets",
        cluster="settings",
        natural_key="code",
        model_class=FakeRecord,
        repository=repo,
        session=session,
        public_fields=["code", "label", "owner_email"],
        secret_fields=frozenset({"secret"}),
        supported_formats=frozenset({"json", NDJSON_FORMAT}),
    )
    return exchanger, repo, session


# ── iter_export ─────────────────────────────────────────────────────────────


def test_iter_export_yields_chunk_sized_batches():
    exchanger, _repo, _session = _make_exchanger(row_count=12)
    chunks = list(
        exchanger.iter_export(ExportSelector(all=True), chunk_size=5, include_pii=True)
    )
    assert [len(chunk) for chunk in chunks] == [5, 5, 2]


def test_iter_export_concatenation_equals_buffered_export():
    exchanger, _repo, _session = _make_exchanger(row_count=7)
    streamed = [
        row
        for chunk in exchanger.iter_export(
            ExportSelector(all=True), chunk_size=3, include_pii=True
        )
        for row in chunk
    ]
    buffered = exchanger.export(ExportSelector(all=True), include_pii=True).rows
    assert streamed == buffered


def test_iter_export_pages_via_iter_rows_not_find_all():
    """The streaming path must use the paged ``iter_rows``, not ``find_all``."""
    exchanger, repo, _session = _make_exchanger(row_count=4)

    def _boom():
        raise AssertionError("iter_export must not call find_all() (no streaming)")

    repo.find_all = _boom  # type: ignore[assignment]
    chunks = list(
        exchanger.iter_export(ExportSelector(all=True), chunk_size=2, include_pii=True)
    )
    assert sum(len(chunk) for chunk in chunks) == 4


# ── NDJSON round-trip parity ─────────────────────────────────────────────────


def test_ndjson_round_trip_matches_buffered_json():
    exporter, _repo, _session = _make_exchanger(row_count=6)
    buffered_rows = exporter.export(ExportSelector(all=True), include_pii=True).rows

    # Build the NDJSON artefact through the streaming writer.
    chunks = exporter.iter_export(
        ExportSelector(all=True), chunk_size=4, include_pii=True
    )
    ndjson_text = "".join(iter_ndjson_lines("widgets", chunks, instance="test"))

    # The first line is the header; the rest are rows.
    lines = ndjson_text.splitlines()
    header = json.loads(lines[0])
    assert header["vbwd_export"] == "widgets"
    assert header["format"] == NDJSON_FORMAT
    parsed_rows = [json.loads(line) for line in lines[1:]]
    assert parsed_rows == buffered_rows


def test_import_ndjson_streams_into_repository():
    exporter, _repo, _session = _make_exchanger(row_count=3)
    chunks = exporter.iter_export(
        ExportSelector(all=True), chunk_size=2, include_pii=True
    )
    ndjson_text = "".join(iter_ndjson_lines("widgets", chunks, instance="test"))

    # Fresh, empty target exchanger.
    target = BaseModelExchanger(
        entity_key="widgets",
        label="Widgets",
        cluster="settings",
        natural_key="code",
        model_class=FakeRecord,
        repository=FakeRepository(),
        session=FakeSession(),
        public_fields=["code", "label", "owner_email"],
        supported_formats=frozenset({"json", NDJSON_FORMAT}),
    )
    result = target.import_ndjson(
        ndjson_text.splitlines(keepends=True),
        mode="upsert",
        dry_run=False,
        chunk_size=2,
    )
    assert result.created == 3
    assert result.updated == 0


def test_import_ndjson_flushes_in_batches():
    """Streaming import flushes per batch so it is never one giant transaction."""
    rows = [FakeRecord(f"c{n}", "L", "", f"u{n}@x") for n in range(5)]
    source_repo = FakeRepository(rows)
    source = BaseModelExchanger(
        entity_key="widgets",
        label="W",
        cluster="settings",
        natural_key="code",
        model_class=FakeRecord,
        repository=source_repo,
        session=FakeSession(),
        public_fields=["code", "label", "owner_email"],
        supported_formats=frozenset({"json", NDJSON_FORMAT}),
    )
    chunks = source.iter_export(
        ExportSelector(all=True), chunk_size=5, include_pii=True
    )
    ndjson_text = "".join(iter_ndjson_lines("widgets", chunks, instance="test"))

    target_session = FakeSession()
    target = BaseModelExchanger(
        entity_key="widgets",
        label="W",
        cluster="settings",
        natural_key="code",
        model_class=FakeRecord,
        repository=FakeRepository(),
        session=target_session,
        public_fields=["code", "label", "owner_email"],
        supported_formats=frozenset({"json", NDJSON_FORMAT}),
    )
    target.import_ndjson(
        ndjson_text.splitlines(keepends=True),
        mode="upsert",
        dry_run=False,
        chunk_size=2,
    )
    # 5 rows at chunk_size 2 → at least two intra-stream flushes before commit.
    assert target_session.flush_count >= 2
    assert target_session.committed is True


# ── malformed line + header validation ───────────────────────────────────────


def test_iter_ndjson_rows_reports_bad_line_number():
    lines = [
        json.dumps({"code": "a"}) + "\n",
        "this is not json\n",
    ]
    iterator = iter_ndjson_rows(iter(lines))
    assert next(iterator) == {"code": "a"}
    with pytest.raises(EnvelopeError) as excinfo:
        next(iterator)
    # Header is line 1; first row line 2; the bad line is line 3.
    assert "line 3" in str(excinfo.value)


def test_validate_ndjson_header_requires_header():
    with pytest.raises(EnvelopeError):
        validate_ndjson_header(iter([]), "widgets")


def test_validate_ndjson_header_rejects_wrong_kind():
    header_line = json.dumps(build_ndjson_header("other_entity", instance="x")) + "\n"
    with pytest.raises(EnvelopeError) as excinfo:
        validate_ndjson_header(iter([header_line]), "widgets")
    assert "widgets" in str(excinfo.value)


def test_import_ndjson_rejects_wrong_header_kind():
    exchanger, _repo, _session = _make_exchanger(row_count=1)
    bad = json.dumps(build_ndjson_header("not_widgets", instance="x")) + "\n"
    with pytest.raises(EnvelopeError):
        exchanger.import_ndjson([bad], mode="upsert", dry_run=False, chunk_size=2)
