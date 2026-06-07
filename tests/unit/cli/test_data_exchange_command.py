"""Specs for the ``flask data-exchange …`` CLI (S46.2).

The CLI is a thin adapter over the same registry + exchanger + envelope code
the admin routes use: it resolves an exchanger from ``data_exchange_registry``,
runs ``export`` / ``import_``, and writes/parses the VBWD-standard envelope.

These tests register a throwaway exchanger into the registry inside the app
context (no DB needed) and drive the command group via ``app.test_cli_runner``.
"""
import json
import os
import tempfile

import pytest

from vbwd.services.data_exchange.envelope import build_envelope
from vbwd.services.data_exchange.port import (
    CLUSTER_SALES,
    CLUSTER_SETTINGS,
    EntityExchanger,
    Envelope,
    ExportSelector,
    ImportResult,
    UnsupportedOperationError,
)
from vbwd.services.data_exchange.registry import data_exchange_registry


class _FakeExchanger(EntityExchanger):
    """An in-memory exchanger keyed by ``code`` for CLI tests."""

    def __init__(
        self,
        *,
        entity_key="widgets",
        cluster=CLUSTER_SALES,
        supported_formats=frozenset({"json", "csv"}),
        supports_import=True,
    ):
        self.entity_key = entity_key
        self.label = entity_key.title()
        self.cluster = cluster
        self.natural_key = "code"
        self.supports_export = True
        self.supports_import = supports_import
        self.supported_formats = frozenset(supported_formats)
        self.secret_fields = frozenset()
        self.pii_fields = frozenset({"owner"})
        self.rows = [{"code": "a", "name": "Alpha", "owner": "ann@example.com"}]
        self.last_import = None

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        rows = []
        for row in self.rows:
            serialised = dict(row)
            if not include_pii:
                for pii_field in self.pii_fields:
                    serialised[pii_field] = None
            rows.append(serialised)
        return Envelope(entity_key=self.entity_key, rows=rows)

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        if not self.supports_import:
            raise UnsupportedOperationError(f"{self.entity_key} is export-only")
        rows = payload.get(self.entity_key, [])
        self.last_import = {"mode": mode, "dry_run": dry_run, "rows": rows}
        if dry_run:
            return ImportResult(
                entity=self.entity_key,
                mode=mode,
                dry_run=True,
                created=len(rows),
            )
        return ImportResult(
            entity=self.entity_key, mode=mode, dry_run=False, created=len(rows)
        )


@pytest.fixture
def registered_exchanger(app):
    """Register a fake exchanger for the duration of one test."""
    exchanger = _FakeExchanger()
    with app.app_context():
        data_exchange_registry.register(exchanger)
    yield exchanger
    data_exchange_registry.unregister(exchanger.entity_key)


# ── list ──────────────────────────────────────────────────────────────────


def test_list_shows_manifest_rows(app, runner, registered_exchanger):
    result = runner.invoke(args=["data-exchange", "list"])
    assert result.exit_code == 0, result.output
    assert "widgets" in result.output
    assert CLUSTER_SALES in result.output


# ── export ─────────────────────────────────────────────────────────────────


def test_export_writes_valid_envelope_to_stdout(app, runner, registered_exchanger):
    result = runner.invoke(args=["data-exchange", "export", "widgets", "--all"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["vbwd_export"] == "widgets"
    assert envelope["version"] == 1
    assert envelope["widgets"][0]["code"] == "a"
    # PII redacted by default.
    assert envelope["widgets"][0]["owner"] is None


def test_export_include_pii_flag_unredacts(app, runner, registered_exchanger):
    result = runner.invoke(
        args=["data-exchange", "export", "widgets", "--all", "--include-pii"]
    )
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["widgets"][0]["owner"] == "ann@example.com"


def test_export_writes_to_outfile(app, runner, registered_exchanger):
    with tempfile.TemporaryDirectory() as tmp:
        outfile = os.path.join(tmp, "out.json")
        result = runner.invoke(
            args=["data-exchange", "export", "widgets", "--all", "-o", outfile]
        )
        assert result.exit_code == 0, result.output
        with open(outfile, encoding="utf-8") as handle:
            envelope = json.load(handle)
        assert envelope["vbwd_export"] == "widgets"


def test_export_csv_for_csv_capable_entity(app, runner, registered_exchanger):
    result = runner.invoke(
        args=["data-exchange", "export", "widgets", "--all", "--format", "csv"]
    )
    assert result.exit_code == 0, result.output
    assert "code" in result.output
    assert "a" in result.output


def test_export_csv_rejected_for_json_only_entity(app, runner):
    exchanger = _FakeExchanger(
        entity_key="jsononly", supported_formats=frozenset({"json"})
    )
    with app.app_context():
        data_exchange_registry.register(exchanger)
    try:
        result = runner.invoke(
            args=["data-exchange", "export", "jsononly", "--all", "--format", "csv"]
        )
        assert result.exit_code != 0
        assert "csv" in result.output.lower()
    finally:
        data_exchange_registry.unregister("jsononly")


def test_export_unknown_entity_errors(app, runner):
    result = runner.invoke(args=["data-exchange", "export", "nope", "--all"])
    assert result.exit_code != 0
    assert "nope" in result.output


# ── import ─────────────────────────────────────────────────────────────────


def _write_envelope_file(tmp, entity_key, rows):
    path = os.path.join(tmp, f"{entity_key}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(build_envelope(entity_key, rows, instance="test"), handle)
    return path


def test_import_upserts_and_prints_counts(app, runner, registered_exchanger):
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_envelope_file(tmp, "widgets", [{"code": "b", "name": "Beta"}])
        result = runner.invoke(args=["data-exchange", "import", "widgets", path])
    assert result.exit_code == 0, result.output
    assert "created" in result.output.lower()
    assert "1" in result.output
    assert registered_exchanger.last_import["dry_run"] is False
    assert registered_exchanger.last_import["mode"] == "upsert"


def test_import_dry_run_passes_flag(app, runner, registered_exchanger):
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_envelope_file(tmp, "widgets", [{"code": "b", "name": "Beta"}])
        result = runner.invoke(
            args=["data-exchange", "import", "widgets", path, "--dry-run"]
        )
    assert result.exit_code == 0, result.output
    assert registered_exchanger.last_import["dry_run"] is True


def test_import_replace_all_warns(app, runner, registered_exchanger):
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_envelope_file(tmp, "widgets", [{"code": "b", "name": "Beta"}])
        result = runner.invoke(
            args=["data-exchange", "import", "widgets", path, "--mode", "replace_all"]
        )
    assert result.exit_code == 0, result.output
    assert "warning" in result.output.lower() or "replace_all" in result.output.lower()
    assert registered_exchanger.last_import["mode"] == "replace_all"


def test_import_export_only_entity_errors(app, runner):
    exchanger = _FakeExchanger(entity_key="reports", supports_import=False)
    with app.app_context():
        data_exchange_registry.register(exchanger)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_envelope_file(tmp, "reports", [{"code": "x"}])
            result = runner.invoke(args=["data-exchange", "import", "reports", path])
        assert result.exit_code != 0
        assert "export-only" in result.output.lower() or "reports" in result.output
    finally:
        data_exchange_registry.unregister("reports")


def test_import_unknown_entity_errors(app, runner):
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_envelope_file(tmp, "nope", [{"code": "x"}])
        result = runner.invoke(args=["data-exchange", "import", "nope", path])
    assert result.exit_code != 0
    assert "nope" in result.output


def test_settings_cluster_exchanger_listed(app, runner):
    exchanger = _FakeExchanger(entity_key="things", cluster=CLUSTER_SETTINGS)
    with app.app_context():
        data_exchange_registry.register(exchanger)
    try:
        result = runner.invoke(args=["data-exchange", "list"])
        assert result.exit_code == 0, result.output
        assert "things" in result.output
        assert CLUSTER_SETTINGS in result.output
    finally:
        data_exchange_registry.unregister("things")
