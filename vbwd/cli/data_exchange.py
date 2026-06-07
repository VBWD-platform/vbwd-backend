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

from vbwd.services.data_exchange.base_model_exchanger import RowCapExceededError
from vbwd.services.data_exchange.envelope import (
    EnvelopeError,
    build_envelope,
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
    type=click.Choice([JSON_FORMAT, CSV_FORMAT]),
    default=JSON_FORMAT,
    help="Output format (csv only for csv-capable entities).",
)
@click.option(
    "--include-pii", is_flag=True, help="Include PII fields (default redacted)."
)
@click.option("-o", "--outfile", default=None, help="Write to file (default stdout).")
@with_appcontext
def export_command(
    entity: str,
    export_all: bool,
    ids: Optional[str],
    export_format: str,
    include_pii: bool,
    outfile: Optional[str],
) -> None:
    """Export ENTITY to a VBWD envelope (JSON or CSV)."""
    exchanger = data_exchange_registry.get(entity)
    if exchanger is None:
        _fail(f"unknown entity '{entity}'")
    if export_format == CSV_FORMAT and CSV_FORMAT not in exchanger.supported_formats:
        _fail(f"entity '{entity}' does not support csv export")

    selector = _build_selector(export_all, ids)
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
        click.echo(f"Wrote {len(rows)} row(s) to {outfile}", err=True)
    else:
        click.echo(output)


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
@with_appcontext
def import_command(entity: str, file: str, mode: str, dry_run: bool) -> None:
    """Import ENTITY from FILE (a VBWD JSON envelope)."""
    exchanger = data_exchange_registry.get(entity)
    if exchanger is None:
        _fail(f"unknown entity '{entity}'")

    if mode == MODE_REPLACE_ALL:
        click.echo(
            f"WARNING: mode=replace_all drops all existing '{entity}' rows "
            "before import.",
            err=True,
        )

    with open(file, encoding="utf-8") as handle:
        try:
            payload = json.load(handle)
        except ValueError as exc:
            _fail(f"invalid JSON file: {exc}")

    try:
        # Fail fast on a malformed envelope so the error is clear (not a stack).
        validate_envelope(payload, entity)
        result = exchanger.import_(payload, mode=mode, dry_run=dry_run)
    except UnsupportedOperationError as exc:
        _fail(str(exc))
    except EnvelopeError as exc:
        _fail(str(exc))

    click.echo(json.dumps(result.to_dict(), indent=2))
