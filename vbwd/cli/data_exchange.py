"""``flask data-exchange export|import|list`` — the operator data-exchange CLI.

A thin adapter over the same registry + ``EntityExchanger`` + envelope code the
admin routes use (DRY). The CLI is an operator tool: it does not go through the
HTTP permission layer, so it exports including PII only when ``--include-pii`` is
passed and allows ``replace_all`` (with a loud warning). It resolves the
exchanger from :data:`data_exchange_registry`, which the app factory populates
with the core exchangers (and plugins with theirs at enable-time) before the
command runs inside the app context.
"""
import json
import sys
from typing import List, NoReturn, Optional

import click
from flask import current_app
from flask.cli import with_appcontext

from vbwd.services.data_exchange import profiling
from vbwd.services.data_exchange.base_model_exchanger import (
    EXPORT_CHUNK_SIZE,
    RowCapExceededError,
)
from vbwd.services.data_exchange.envelope import (
    EnvelopeError,
    NDJSON_FORMAT,
    build_envelope,
    iter_ndjson_lines,
    rows_to_csv,
    validate_envelope,
)
from vbwd.services.data_exchange.port import (
    MODE_REPLACE_ALL,
    MODE_UPSERT,
    ExportSelector,
    UnsupportedOperationError,
)
from vbwd.services.data_exchange.registry import data_exchange_registry

# Exit codes (mirrors ``flask seed``'s contract).
EXIT_OK = 0
EXIT_ERROR = 1

JSON_FORMAT = "json"
CSV_FORMAT = "csv"


def _instance_name() -> str:
    return current_app.config.get("VBWD_INSTANCE", "default")


def _fail(message: str) -> NoReturn:
    """Print an error to stderr and abort the command with a nonzero exit."""
    click.echo(f"Error: {message}", err=True)
    sys.exit(EXIT_ERROR)


@click.group("data-exchange")
def data_exchange_group() -> None:
    """Export and import entity data through the unified data-exchange seam."""


@data_exchange_group.command("list")
@with_appcontext
def list_command() -> None:
    """Print the registry manifest (entity, cluster, formats, export/import)."""
    exchangers = sorted(
        data_exchange_registry.all(),
        key=lambda exchanger: (exchanger.cluster, exchanger.entity_key),
    )
    if not exchangers:
        click.echo("No exchangers registered.")
        return
    for exchanger in exchangers:
        formats = ",".join(sorted(exchanger.supported_formats))
        export_flag = "export" if exchanger.supports_export else "-"
        import_flag = "import" if exchanger.supports_import else "-"
        click.echo(
            f"{exchanger.entity_key}\t{exchanger.cluster}\t"
            f"[{formats}]\t{export_flag}/{import_flag}"
        )


@data_exchange_group.command("export")
@click.argument("entity")
@click.option("--all", "export_all", is_flag=True, help="Export every row.")
@click.option("--ids", default=None, help="Comma-separated natural keys to export.")
@click.option(
    "--format",
    "export_format",
    type=click.Choice([JSON_FORMAT, CSV_FORMAT, NDJSON_FORMAT]),
    default=JSON_FORMAT,
    help="Output format (csv only for csv-capable entities; ndjson streams).",
)
@click.option(
    "--include-pii", is_flag=True, help="Include PII fields (default redacted)."
)
@click.option("-o", "--outfile", default=None, help="Write to file (default stdout).")
@click.option(
    "--profile-json",
    is_flag=True,
    help="Print the server-side stage-timing split to stderr (load env only).",
)
@with_appcontext
def export_command(
    entity: str,
    export_all: bool,
    ids: Optional[str],
    export_format: str,
    include_pii: bool,
    outfile: Optional[str],
    profile_json: bool,
) -> None:
    """Export ENTITY to a VBWD envelope (JSON, CSV, or streamed NDJSON)."""
    exchanger = data_exchange_registry.get(entity)
    if exchanger is None:
        _fail(f"unknown entity '{entity}'")
    if export_format == CSV_FORMAT and CSV_FORMAT not in exchanger.supported_formats:
        _fail(f"entity '{entity}' does not support csv export")

    selector = _build_selector(export_all, ids)
    with profiling.start_operation(**_profile_target(exchanger)) as stage_profile:
        if export_format == NDJSON_FORMAT:
            row_count = _export_ndjson(
                exchanger, entity, selector, include_pii, outfile
            )
        else:
            row_count = _export_buffered(
                exchanger, entity, selector, export_format, include_pii, outfile
            )
    _maybe_print_profile(profile_json, stage_profile)
    if outfile and export_format != NDJSON_FORMAT:
        click.echo(f"Wrote {row_count} row(s) to {outfile}", err=True)


def _export_buffered(
    exchanger,
    entity: str,
    selector: ExportSelector,
    export_format: str,
    include_pii: bool,
    outfile: Optional[str],
) -> int:
    """Buffered JSON/CSV export (the small/UI path). Returns the row count."""
    try:
        rows = exchanger.export(selector, include_pii=include_pii).rows
    except UnsupportedOperationError as exc:
        _fail(str(exc))
    except RowCapExceededError as exc:
        _fail(str(exc))

    if export_format == CSV_FORMAT:
        output = rows_to_csv(rows)
    else:
        envelope = build_envelope(entity, rows, instance=_instance_name())
        output = json.dumps(envelope, default=str, indent=2)

    if outfile:
        with open(outfile, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        click.echo(output)
    return len(rows)


def _export_ndjson(
    exchanger,
    entity: str,
    selector: ExportSelector,
    include_pii: bool,
    outfile: Optional[str],
) -> int:
    """Streamed NDJSON export: header line then one row per line. O(1) memory."""
    row_count = 0
    try:
        chunks = exchanger.iter_export(
            selector, chunk_size=EXPORT_CHUNK_SIZE, include_pii=include_pii
        )
        lines = iter_ndjson_lines(entity, chunks, instance=_instance_name())
        if outfile:
            with open(outfile, "w", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(line)
                    row_count += 1
        else:
            for line in lines:
                click.echo(line, nl=False)
                row_count += 1
    except UnsupportedOperationError as exc:
        _fail(str(exc))
    except RowCapExceededError as exc:
        _fail(str(exc))
    # The first line is the header; rows are the remainder.
    rows_written = max(row_count - 1, 0)
    if outfile:
        click.echo(f"Wrote {rows_written} row(s) to {outfile}", err=True)
    return rows_written


def _profile_target(exchanger) -> dict:
    """Profiler kwargs (table + session) for sizing the right table at op end.

    Best-effort: an exchanger without these attributes simply yields ``{}`` so the
    catalog/size fields stay ``None`` (the profiler is load-gated anyway).
    """
    target: dict = {}
    table_name = getattr(exchanger, "table_name", None)
    session = getattr(exchanger, "session", None)
    if table_name is not None:
        target["table_name"] = table_name
    if session is not None:
        target["session"] = session
    return target


def _maybe_print_profile(enabled: bool, stage_profile) -> None:
    """Emit the stage-timing one-liner to stderr when asked + the load flag is on."""
    if enabled and profiling.profiling_enabled():
        click.echo(json.dumps({"_profile": stage_profile.to_dict()}), err=True)


def _build_selector(export_all: bool, ids: Optional[str]) -> ExportSelector:
    """Map ``--all`` / ``--ids`` to an :class:`ExportSelector`."""
    if ids:
        id_list: List[str] = [
            value.strip() for value in ids.split(",") if value.strip()
        ]
        return ExportSelector(ids=id_list)
    return ExportSelector(all=export_all)


@data_exchange_group.command("import")
@click.argument("entity")
@click.argument("file", type=click.Path(exists=True))
@click.option(
    "--mode",
    type=click.Choice([MODE_UPSERT, MODE_REPLACE_ALL]),
    default=MODE_UPSERT,
    help="Upsert by natural key (default) or drop-then-import (replace_all).",
)
@click.option("--dry-run", is_flag=True, help="Compute counts without writing.")
@click.option(
    "--format",
    "import_format",
    type=click.Choice([JSON_FORMAT, NDJSON_FORMAT]),
    default=None,
    help="Force the input format (default: inferred from the .ndjson suffix).",
)
@click.option(
    "--profile-json",
    is_flag=True,
    help="Print the server-side stage-timing split to stderr (load env only).",
)
@with_appcontext
def import_command(
    entity: str,
    file: str,
    mode: str,
    dry_run: bool,
    import_format: Optional[str],
    profile_json: bool,
) -> None:
    """Import ENTITY from FILE (a VBWD JSON envelope or a streamed NDJSON file)."""
    exchanger = data_exchange_registry.get(entity)
    if exchanger is None:
        _fail(f"unknown entity '{entity}'")

    if mode == MODE_REPLACE_ALL:
        click.echo(
            f"WARNING: mode=replace_all drops all existing '{entity}' rows "
            "before import.",
            err=True,
        )

    resolved_format = import_format or (
        NDJSON_FORMAT if file.endswith(".ndjson") else JSON_FORMAT
    )

    with profiling.start_operation(**_profile_target(exchanger)) as stage_profile:
        if resolved_format == NDJSON_FORMAT:
            result = _import_ndjson(exchanger, file, mode, dry_run)
        else:
            result = _import_buffered(exchanger, entity, file, mode, dry_run)
    _maybe_print_profile(profile_json, stage_profile)
    click.echo(json.dumps(result.to_dict(), indent=2))


def _import_buffered(exchanger, entity: str, file: str, mode: str, dry_run: bool):
    """Import a buffered VBWD JSON envelope file."""
    with open(file, encoding="utf-8") as handle:
        try:
            payload = json.load(handle)
        except ValueError as exc:
            _fail(f"invalid JSON file: {exc}")
    try:
        # Fail fast on a malformed envelope so the error is clear (not a stack).
        validate_envelope(payload, entity)
        return exchanger.import_(payload, mode=mode, dry_run=dry_run)
    except UnsupportedOperationError as exc:
        _fail(str(exc))
    except EnvelopeError as exc:
        _fail(str(exc))


def _import_ndjson(exchanger, file: str, mode: str, dry_run: bool):
    """Stream-import an NDJSON file line-by-line (header validated, bounded memory)."""
    try:
        with open(file, encoding="utf-8") as handle:
            return exchanger.import_ndjson(
                handle, mode=mode, dry_run=dry_run, chunk_size=EXPORT_CHUNK_SIZE
            )
    except UnsupportedOperationError as exc:
        _fail(str(exc))
    except EnvelopeError as exc:
        _fail(str(exc))


@data_exchange_group.command("bulk-seed")
@click.argument("entity")
@click.option("--count", type=int, required=True, help="How many load-test rows.")
@click.option(
    "--reset",
    is_flag=True,
    help="Drop existing loadtest-prefixed rows first (never real/demo data).",
)
@click.option(
    "--batch-size",
    type=int,
    default=None,
    help="Rows per commit (defaults to the exchanger's batch size).",
)
@with_appcontext
def bulk_seed_command(
    entity: str,
    count: int,
    reset: bool,
    batch_size: Optional[int],
) -> None:
    """Generate COUNT deterministic load-test rows for ENTITY through the repo.

    Idempotent (re-running with the same COUNT is a no-op upsert); ``--reset``
    drops only the ``loadtest-``-prefixed rows. Inserts in batches through the
    repository's bulk API — never raw SQL.
    """
    exchanger = data_exchange_registry.get(entity)
    if exchanger is None:
        _fail(f"unknown entity '{entity}'")
    if count < 0:
        _fail("--count must be zero or positive")

    seed_kwargs: dict = {"reset": reset}
    if batch_size is not None:
        seed_kwargs["batch_size"] = batch_size
    try:
        result = exchanger.bulk_seed(count, **seed_kwargs)
    except UnsupportedOperationError as exc:
        _fail(str(exc))
    click.echo(json.dumps(result.to_dict(), indent=2))
