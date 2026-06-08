"""The EntityExchanger port + its data carriers.

An ``EntityExchanger`` is the single contract every importable/exportable
entity implements (core entities and plugin entities alike). The seam is
generic: an exchanger declares *what* it can do (formats, secret/PII fields,
cluster) and *how* to (de)serialise; the registry, routes, and CLI drive it
without naming any domain.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

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
