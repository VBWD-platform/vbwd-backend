"""S89 CLI specs — NDJSON export/import + the bulk-seed generator.

Extends the ``flask data-exchange`` group (does not rewrite it): drives the new
``--format ndjson`` export, the streaming NDJSON import, and the ``bulk-seed``
subcommand through ``app.test_cli_runner`` with throwaway exchangers registered
into ``data_exchange_registry`` (no DB).
"""
import json
import os
import tempfile

import pytest

from vbwd.services.data_exchange.base_model_exchanger import (
    LOADTEST_SLUG_PREFIX,
    BaseModelExchanger,
)
from vbwd.services.data_exchange.envelope import NDJSON_FORMAT
from vbwd.services.data_exchange.port import (
    CLUSTER_SALES,
    EntityExchanger,
    Envelope,
    ExportSelector,
    ImportResult,
    UnsupportedOperationError,
)
from vbwd.services.data_exchange.registry import data_exchange_registry

from tests.unit.data_exchange.fakes import FakeRecord, FakeRepository, FakeSession


def _make_base_exchanger(entity_key="widgets", rows=None):
    repo = FakeRepository(rows or [])
    session = FakeSession()
    return (
        BaseModelExchanger(
            entity_key=entity_key,
            label=entity_key.title(),
            cluster=CLUSTER_SALES,
            natural_key="code",
            model_class=FakeRecord,
            repository=repo,
            session=session,
            public_fields=["code", "label"],
            supported_formats=frozenset({"json", "csv", NDJSON_FORMAT}),
        ),
        repo,
        session,
    )


@pytest.fixture
def registered_base_exchanger(app):
    rows = [FakeRecord("a", "Alpha"), FakeRecord("b", "Beta")]
    exchanger, _repo, _session = _make_base_exchanger(rows=rows)
    with app.app_context():
        data_exchange_registry.register(exchanger)
    yield exchanger
    data_exchange_registry.unregister(exchanger.entity_key)


# ── NDJSON export ────────────────────────────────────────────────────────────


def test_export_ndjson_to_outfile(app, runner, registered_base_exchanger):
    with tempfile.TemporaryDirectory() as tmp:
        outfile = os.path.join(tmp, "out.ndjson")
        result = runner.invoke(
            args=[
                "data-exchange",
                "export",
                "widgets",
                "--all",
                "--format",
                "ndjson",
                "-o",
                outfile,
            ]
        )
        assert result.exit_code == 0, result.output
        with open(outfile, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    header = json.loads(lines[0])
    assert header["vbwd_export"] == "widgets"
    assert header["format"] == NDJSON_FORMAT
    rows = [json.loads(line) for line in lines[1:]]
    assert sorted(row["code"] for row in rows) == ["a", "b"]


def test_export_ndjson_to_stdout(app, runner, registered_base_exchanger):
    result = runner.invoke(
        args=["data-exchange", "export", "widgets", "--all", "--format", "ndjson"]
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    header = json.loads(lines[0])
    assert header["format"] == NDJSON_FORMAT


# ── NDJSON import (streamed) ─────────────────────────────────────────────────


def test_import_ndjson_round_trips(app, runner):
    rows = [FakeRecord("a", "Alpha"), FakeRecord("b", "Beta"), FakeRecord("c", "Gamma")]
    exchanger, repo, _session = _make_base_exchanger(rows=rows)
    with app.app_context():
        data_exchange_registry.register(exchanger)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            artefact = os.path.join(tmp, "widgets.ndjson")
            export_result = runner.invoke(
                args=[
                    "data-exchange",
                    "export",
                    "widgets",
                    "--all",
                    "--format",
                    "ndjson",
                    "-o",
                    artefact,
                ]
            )
            assert export_result.exit_code == 0, export_result.output

            # Re-import into a fresh empty target registered under the same key.
            data_exchange_registry.unregister("widgets")
            target, target_repo, _ = _make_base_exchanger()
            with app.app_context():
                data_exchange_registry.register(target)
            import_result = runner.invoke(
                args=["data-exchange", "import", "widgets", artefact]
            )
        assert import_result.exit_code == 0, import_result.output
        payload = json.loads(import_result.output)
        assert payload["created"] == 3
        assert sorted(record.code for record in target_repo.find_all()) == [
            "a",
            "b",
            "c",
        ]
    finally:
        data_exchange_registry.unregister("widgets")


# ── bulk-seed ────────────────────────────────────────────────────────────────


def test_bulk_seed_creates_rows(app, runner):
    exchanger, repo, _session = _make_base_exchanger()
    with app.app_context():
        data_exchange_registry.register(exchanger)
    try:
        result = runner.invoke(
            args=["data-exchange", "bulk-seed", "widgets", "--count", "5"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["created"] == 5
        assert all(
            record.code.startswith(LOADTEST_SLUG_PREFIX) for record in repo.find_all()
        )
    finally:
        data_exchange_registry.unregister("widgets")


def test_bulk_seed_reset_is_idempotent(app, runner):
    exchanger, repo, _session = _make_base_exchanger()
    with app.app_context():
        data_exchange_registry.register(exchanger)
    try:
        runner.invoke(args=["data-exchange", "bulk-seed", "widgets", "--count", "5"])
        result = runner.invoke(
            args=["data-exchange", "bulk-seed", "widgets", "--count", "5", "--reset"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["deleted"] == 5
        assert payload["created"] == 5
        assert len(repo.find_all()) == 5
    finally:
        data_exchange_registry.unregister("widgets")


def test_bulk_seed_unknown_entity_errors(app, runner):
    result = runner.invoke(args=["data-exchange", "bulk-seed", "nope", "--count", "5"])
    assert result.exit_code != 0
    assert "nope" in result.output


def test_bulk_seed_export_only_entity_errors(app, runner):
    class _ExportOnly(EntityExchanger):
        entity_key = "reports"
        label = "Reports"
        cluster = CLUSTER_SALES
        natural_key = "code"
        supports_export = True
        supports_import = False
        supported_formats = frozenset({"json"})

        def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
            return Envelope(entity_key=self.entity_key, rows=[])

        def import_(self, payload, *, mode, dry_run) -> ImportResult:
            raise UnsupportedOperationError("export-only")

    with app.app_context():
        data_exchange_registry.register(_ExportOnly())
    try:
        result = runner.invoke(
            args=["data-exchange", "bulk-seed", "reports", "--count", "5"]
        )
        assert result.exit_code != 0
        assert "bulk-seed" in result.output or "reports" in result.output
    finally:
        data_exchange_registry.unregister("reports")
