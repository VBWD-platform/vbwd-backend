"""Generic concrete EntityExchanger for the common one-model + one-repo case.

Most core and plugin entities are "one BaseModel, one repository, upsert by a
natural key". ``BaseModelExchanger`` implements that shape once (DRY): export
strips UUIDs + secrets, redacts PII unless permitted, maps FKs to their
referent's natural key, honours the selector + row cap; import upserts by
natural key (``replace_all`` drops first), with ``dry_run`` rolling back.

Entities with bespoke shaping (nested 1:1, ZIP+assets) subclass and override
``export`` / ``import_`` — extension, not core change.
"""
from typing import Any, Callable, Dict, FrozenSet, List, Optional

from vbwd.services.data_exchange.envelope import validate_envelope
from vbwd.services.data_exchange.port import (
    MODE_REPLACE_ALL,
    EntityExchanger,
    Envelope,
    ExportSelector,
    ImportResult,
)

# Default per-entity export/import row cap (D8); config-overridable per call.
DEFAULT_ROW_CAP = 10000


class RowCapExceededError(Exception):
    """Raised when an export would emit more rows than the configured cap."""


class BaseModelExchanger(EntityExchanger):
    """Generic exchanger over a single model + repository."""

    def __init__(
        self,
        *,
        entity_key: str,
        label: str,
        cluster: str,
        natural_key: str,
        model_class: type,
        repository: Any,
        session: Any,
        public_fields: List[str],
        secret_fields: FrozenSet[str] = frozenset(),
        pii_fields: FrozenSet[str] = frozenset(),
        fk_natural_key_map: Optional[Dict[str, Callable[[Any], Any]]] = None,
        supported_formats: FrozenSet[str] = frozenset({"json"}),
        supports_export: bool = True,
        supports_import: bool = True,
        row_cap: int = DEFAULT_ROW_CAP,
    ) -> None:
        self.entity_key = entity_key
        self.label = label
        self.cluster = cluster
        self.natural_key = natural_key
        self.supports_export = supports_export
        self.supports_import = supports_import
        self.supported_formats = frozenset(supported_formats)
        self.secret_fields = frozenset(secret_fields)
        self.pii_fields = frozenset(pii_fields)
        self._model_class = model_class
        self._repository = repository
        self._session = session
        self._public_fields = list(public_fields)
        self._fk_natural_key_map = dict(fk_natural_key_map or {})
        self._row_cap = row_cap

    # ── export ───────────────────────────────────────────────────────────

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        rows = self._select_rows(selector)
        if len(rows) > self._row_cap:
            raise RowCapExceededError(
                f"{self.entity_key}: {len(rows)} rows exceeds cap "
                f"{self._row_cap}; narrow with filters"
            )
        serialised = [self._serialise_row(row, include_pii=include_pii) for row in rows]
        return Envelope(entity_key=self.entity_key, rows=serialised)

    def _select_rows(self, selector: ExportSelector) -> List[Any]:
        all_rows = self._repository.find_all()
        if selector.ids:
            wanted = {str(value) for value in selector.ids}
            return [row for row in all_rows if self._row_selected(row, wanted)]
        return all_rows

    def _row_selected(self, row: Any, wanted: set) -> bool:
        """A row matches when its primary id OR its natural key is requested.

        The fe-admin "Export selected" sends primary-key ids; the CLI ``--ids``
        flag may pass natural keys. Both sides are stringified for UUID safety.
        """
        primary_id = getattr(row, "id", None)
        natural_value = getattr(row, self.natural_key, None)
        return (primary_id is not None and str(primary_id) in wanted) or (
            natural_value is not None and str(natural_value) in wanted
        )

    def _serialise_row(self, row: Any, *, include_pii: bool) -> dict:
        result: dict = {}
        for field_name in self._public_fields:
            if field_name in self.secret_fields:
                continue
            value = getattr(row, field_name)
            if field_name in self.pii_fields and not include_pii:
                value = None
            result[field_name] = value
        for fk_field, resolver in self._fk_natural_key_map.items():
            result[fk_field] = resolver(row)
        return result

    # ── import ───────────────────────────────────────────────────────────

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        rows = validate_envelope(payload, self.entity_key)
        result = ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)
        # Dry-run never mutates: it probes (find existing) to project counts but
        # writes nothing, so it is side-effect-free even for a non-transactional
        # repository. A real session is also rolled back below for safety.
        try:
            if mode == MODE_REPLACE_ALL and not dry_run:
                self._repository.delete_all()
            for index, row in enumerate(rows):
                self._import_row(row, index, result, dry_run=dry_run)
        except Exception:
            self._session.rollback()
            raise
        if dry_run:
            self._session.rollback()
        else:
            self._session.commit()
        return result

    def _import_row(
        self, row: dict, index: int, result: ImportResult, *, dry_run: bool
    ) -> None:
        key_value = row.get(self.natural_key)
        if not key_value:
            result.errors.append(
                {"row": index, "reason": f"missing natural key '{self.natural_key}'"}
            )
            return
        # replace_all dry-run: the table is conceptually emptied first, so every
        # row counts as a create even if a same-key row currently exists.
        replace_dry_run = dry_run and result.mode == MODE_REPLACE_ALL
        existing = (
            None if replace_dry_run else self._repository.find_by_natural_key(key_value)
        )
        if existing is not None:
            if not dry_run:
                for field_name, value in row.items():
                    if field_name in self.secret_fields:
                        continue
                    setattr(existing, field_name, value)
            result.updated += 1
        else:
            if not dry_run:
                instance = self._build_instance(row)
                self._repository.add(instance)
            result.created += 1

    def _build_instance(self, row: dict) -> Any:
        attributes = {
            field_name: value
            for field_name, value in row.items()
            if field_name not in self.secret_fields
        }
        return self._model_class(**attributes)
