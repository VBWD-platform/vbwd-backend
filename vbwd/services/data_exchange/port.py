"""The EntityExchanger port + its data carriers.

An ``EntityExchanger`` is the single contract every importable/exportable
entity implements (core entities and plugin entities alike). The seam is
generic: an exchanger declares *what* it can do (formats, secret/PII fields,
cluster) and *how* to (de)serialise; the registry, routes, and CLI drive it
without naming any domain.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional

# The two UI groupings an exchanger may declare. Generic, not domain vocabulary.
CLUSTER_SALES = "sales"
CLUSTER_SETTINGS = "settings"

# Import modes (D4/R5).
MODE_UPSERT = "upsert"
MODE_REPLACE_ALL = "replace_all"


class UnsupportedOperationError(Exception):
    """Raised when an exchanger is asked for a structurally unsupported op.

    Liskov: an export-only exchanger raises this from ``import_`` rather than
    silently returning a failure result, so the caller decides how to respond.
    """


@dataclass
class ExportSelector:
    """Which rows to export (D7): explicit ids, a filter map, or all rows."""

    ids: Optional[List[str]] = None
    filters: Optional[dict] = None
    all: bool = False


@dataclass
class Envelope:
    """An exchanger's export output: the entity key and its serialised rows.

    The route/CLI layer wraps these rows in the VBWD-standard JSON/CSV envelope
    (see :mod:`vbwd.services.data_exchange.envelope`) — the exchanger only
    produces the instance-independent row dicts.
    """

    entity_key: str
    rows: List[dict] = field(default_factory=list)


@dataclass
class ZipExport:
    """A zip export's payload: the row dicts plus the binary assets they name.

    ``rows`` are the instance-independent row dicts (the route wraps them in a
    JSON envelope); ``assets`` maps an asset filename to its raw bytes, written
    into the bundle's ``assets/`` directory. An exchanger with no binaries
    returns an empty ``assets`` map (the default below), so a plain exchanger is
    zip-capable without any binary handling.
    """

    rows: List[dict] = field(default_factory=list)
    assets: Dict[str, bytes] = field(default_factory=dict)


@dataclass
class BulkSeedResult:
    """Outcome of the load-test bulk-seed generator (S89 Slice 2)."""

    entity: str
    created: int = 0
    skipped: int = 0
    deleted: int = 0

    def to_dict(self) -> dict:
        return {
            "entity": self.entity,
            "created": self.created,
            "skipped": self.skipped,
            "deleted": self.deleted,
        }


@dataclass
class ImportResult:
    """Uniform import outcome (mirrors the spec's result shape)."""

    entity: str
    mode: str
    dry_run: bool
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entity": self.entity,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


class EntityExchanger(ABC):
    """Contract for exporting/importing one entity.

    Concrete attributes (set on the subclass): ``entity_key``, ``label``,
    ``cluster``, ``natural_key``, ``supports_export``, ``supports_import``,
    ``supported_formats``, ``secret_fields``, ``pii_fields``.
    """

    entity_key: str
    label: str
    cluster: str
    natural_key: str
    supports_export: bool = True
    supports_import: bool = True
    supported_formats: frozenset = frozenset({"json"})
    secret_fields: frozenset = frozenset()
    pii_fields: frozenset = frozenset()

    @abstractmethod
    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        """Serialise the selected rows (UUIDs/secrets stripped, FK→natural key).

        ``include_pii`` is False unless the caller holds the PII permission, in
        which case the exchanger redacts its ``pii_fields``.
        """

    @abstractmethod
    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        """Upsert (or replace-all) the payload's rows by natural key.

        Export-only exchangers raise :class:`UnsupportedOperationError`.
        ``dry_run`` computes counts then rolls back (never writes).
        """

    def iter_export(
        self,
        selector: ExportSelector,
        *,
        chunk_size: int,
        include_pii: bool,
    ) -> Iterator[List[dict]]:
        """Stream the export in ``chunk_size`` batches (S89 Slice 1).

        Optional hook. The default wraps :meth:`export` and yields its rows as a
        single chunk, so every exchanger is NDJSON-streamable; an exchanger over
        a large table overrides this to page the query (bounded memory). The
        concatenation of the yielded chunks equals ``export().rows`` (Liskov).
        """
        yield self.export(selector, include_pii=include_pii).rows

    def import_ndjson(
        self,
        lines: Iterable[str],
        *,
        mode: str,
        dry_run: bool,
        chunk_size: int,
    ) -> "ImportResult":
        """Stream-import an NDJSON artefact (header line + one row per line).

        Optional hook. An export-only exchanger raises
        :class:`UnsupportedOperationError`; an importable one streams the rows in
        ``chunk_size`` batches so import is bounded-memory. The default buffers
        the rows and delegates to :meth:`import_` (correct, not yet streaming) so
        any exchanger supports NDJSON import out of the box.
        """
        from vbwd.services.data_exchange.envelope import (
            ENVELOPE_KEY,
            iter_ndjson_rows,
            validate_ndjson_header,
        )

        line_iterator = iter(lines)
        validate_ndjson_header(line_iterator, self.entity_key)
        rows = list(iter_ndjson_rows(line_iterator))
        payload = {ENVELOPE_KEY: self.entity_key, self.entity_key: rows}
        return self.import_(payload, mode=mode, dry_run=dry_run)

    def bulk_seed(
        self,
        count: int,
        *,
        reset: bool = False,
        batch_size: int = 1000,
    ) -> "BulkSeedResult":
        """Generate ``count`` deterministic load-test rows (S89 Slice 2).

        Optional hook. An exchanger that cannot manufacture rows (export-only, or
        a structurally non-seedable entity) raises
        :class:`UnsupportedOperationError` rather than silently doing nothing
        (Liskov). :class:`BaseModelExchanger` implements the generic case.
        """
        raise UnsupportedOperationError(f"{self.entity_key} does not support bulk-seed")

    def export_zip(self, selector: ExportSelector, *, include_pii: bool) -> ZipExport:
        """Export rows plus their binary assets for a ZIP bundle.

        Optional hook. The default wraps :meth:`export` and carries no assets,
        so every exchanger is zip-capable with no binary handling; an exchanger
        with files on disk overrides this to reference each binary by an
        ``assets/`` filename and return the raw bytes alongside.
        """
        return ZipExport(
            rows=self.export(selector, include_pii=include_pii).rows, assets={}
        )

    def attach_assets(self, envelope: dict, assets: dict) -> dict:
        """Re-inline a bundle's binary assets into the envelope before import.

        Optional hook (the reverse of :meth:`export_zip`). The default returns
        the envelope unchanged, so non-binary entities import from a bundle as-is;
        a binary exchanger overrides this to map each row's asset reference back
        to the bytes the existing :meth:`import_` path expects.
        """
        return envelope

    @property
    def export_permission(self) -> str:
        return f"{self.entity_key}.export"

    @property
    def import_permission(self) -> str:
        return f"{self.entity_key}.import"

    @property
    def pii_export_permission(self) -> str:
        return f"{self.entity_key}.export.pii"
