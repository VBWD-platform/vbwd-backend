"""Generic concrete EntityExchanger for the common one-model + one-repo case.

Most core and plugin entities are "one BaseModel, one repository, upsert by a
natural key". ``BaseModelExchanger`` implements that shape once (DRY): export
strips UUIDs + secrets, redacts PII unless permitted, maps FKs to their
referent's natural key, honours the selector + row cap; import upserts by
natural key (``replace_all`` drops first), with ``dry_run`` rolling back.

Entities with bespoke shaping (nested 1:1, ZIP+assets) subclass and override
``export`` / ``import_`` — extension, not core change.

S89 (heavy-load data-exchange) adds three load-bearing affordances on top of
the same contract, without changing it:

* a **configurable default row cap** (env ``VBWD_DATA_EXCHANGE_ROW_CAP``) so the
  harness can lift the 10k guard for a measured run while production stays
  protected;
* a **chunked iterator** (:meth:`iter_export`) that pages the query instead of
  materialising every row, plus a **streaming NDJSON import** so both ends are
  bounded-memory at 100k rows; ``export`` / ``import_`` are reimplemented on top
  of these (Liskov-preserving — same observable result);
* an optional **bulk seed** hook for the load-test data generator.
"""
import os
from enum import Enum
from typing import Any, Callable, Dict, FrozenSet, Iterable, Iterator, List, Optional

from vbwd.services.data_exchange import profiling
from vbwd.services.data_exchange.envelope import (
    iter_ndjson_rows,
    validate_envelope,
    validate_ndjson_header,
)
from vbwd.services.data_exchange.port import (
    MODE_REPLACE_ALL,
    BulkSeedResult,
    EntityExchanger,
    Envelope,
    ExportSelector,
    ImportResult,
)

# Default per-entity export/import row cap (D8); config-overridable per call.
DEFAULT_ROW_CAP = 10000

# Env var the load harness sets to lift the cap for a measured run (S89 Slice 0).
ROW_CAP_ENV_VAR = "VBWD_DATA_EXCHANGE_ROW_CAP"

# How many rows one streaming export/import batch carries (S89 Slice 1). Bounds
# peak memory to a chunk rather than the whole dataset; a named constant, not a
# magic number sprinkled at the call sites.
EXPORT_CHUNK_SIZE = 5000

# Default batch size for the load-test bulk seed (S89 Slice 2) — commit
# incrementally so a 100k seed is never one giant transaction.
SEED_BATCH_SIZE = 1000

# Prefix every load-test row carries in its natural key, so ``--reset`` can drop
# exactly those and never touch real/demo data (S89 Slice 2).
LOADTEST_SLUG_PREFIX = "loadtest-"


class RowCapExceededError(Exception):
    """Raised when an export would emit more rows than the configured cap."""


def resolve_default_row_cap() -> int:
    """Return the per-process default row cap.

    Reads ``VBWD_DATA_EXCHANGE_ROW_CAP`` once: a positive integer overrides the
    safe default; anything else (unset, ``0``, negative, or garbage) falls back
    to :data:`DEFAULT_ROW_CAP` without crashing. Production leaves the var unset
    and keeps the 10k guard; the load harness exports a large value for a run.
    """
    raw = os.environ.get(ROW_CAP_ENV_VAR)
    if not raw:
        return DEFAULT_ROW_CAP
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_ROW_CAP
    if parsed <= 0:
        return DEFAULT_ROW_CAP
    return parsed


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
        row_cap: Optional[int] = None,
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
        # ``None`` means "use the env-resolved default"; an explicit int (e.g. a
        # test or a per-entity override) wins. Resolved once at construction.
        self._row_cap = resolve_default_row_cap() if row_cap is None else row_cap

    @property
    def table_name(self) -> Optional[str]:
        """The model's SQL ``__tablename__`` (for the profiler's size query)."""
        return getattr(self._model_class, "__tablename__", None)

    @property
    def session(self) -> Any:
        """The SQLAlchemy session backing this exchanger (profiler catalog query)."""
        return self._session

    # ── export ───────────────────────────────────────────────────────────

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        """Buffered export (the UI default): drains :meth:`iter_export` into a list.

        Reimplemented on top of the chunked iterator (DRY) so its contract is
        unchanged (Liskov): same rows, same cap behaviour. Small/UI exports use
        this; the heavy-load NDJSON path uses :meth:`iter_export` directly.
        """
        serialised: List[dict] = []
        for chunk in self.iter_export(
            selector, chunk_size=EXPORT_CHUNK_SIZE, include_pii=include_pii
        ):
            serialised.extend(chunk)
        return Envelope(entity_key=self.entity_key, rows=serialised)

    def iter_export(
        self,
        selector: ExportSelector,
        *,
        chunk_size: int = EXPORT_CHUNK_SIZE,
        include_pii: bool,
    ) -> Iterator[List[dict]]:
        """Yield serialised rows in ``chunk_size`` batches, paging the query.

        Never calls ``.all()`` on the full set: it walks the repository's paged
        stream (``iter_rows``/``yield_per``), enforces the row cap as it counts,
        and serialises one chunk at a time so peak memory is bounded by
        ``chunk_size`` rather than by the total row count. The row cap is checked
        against the running count so an oversized export is rejected early.

        Only the per-row dict-building is timed as the ``serialise`` stage; the
        DB paging stays outside the span so the cursor hook (which times the SQL)
        and the serialise span do not double-count the same wall-clock.
        """
        emitted = 0
        chunk: List[dict] = []
        for row in self._iter_selected_rows(selector):
            emitted += 1
            if emitted > self._row_cap:
                raise RowCapExceededError(
                    f"{self.entity_key}: more than {self._row_cap} rows "
                    "exceeds cap; narrow with filters"
                )
            with profiling.span(profiling.SPAN_SERIALISE):
                chunk.append(self._serialise_row(row, include_pii=include_pii))
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

    def _iter_selected_rows(self, selector: ExportSelector) -> Iterator[Any]:
        """Stream the selected rows, paging the repository instead of ``.all()``.

        Uses the repository's ``iter_rows`` (keyset/``yield_per`` paging) when it
        offers one; otherwise falls back to the legacy ``find_all`` (small/fake
        repos). The id-selector filter is applied on the stream so a selected
        export still streams.
        """
        wanted = {str(value) for value in selector.ids} if selector.ids else None
        for row in self._row_stream():
            if wanted is None or self._row_selected(row, wanted):
                yield row

    def _row_stream(self) -> Iterable[Any]:
        """Stream every row in bounded-memory pages, surviving session teardown.

        The HTTP NDJSON export drives this lazily under ``stream_with_context``,
        so iteration continues *after* the view has returned. A server-side
        ``yield_per`` cursor is bound to the session connection and is
        invalidated the moment the app-context teardown runs ``session.remove()``
        (or the connection is otherwise reset) mid-stream — psycopg2 then raises
        "named cursor isn't valid anymore" and the stream truncates silently at a
        chunk boundary (the S89 load-test finding: bookings 0 rows, plans/products
        partial, smaller tables whole). Keyset pagination avoids that: each page
        is an independent ``ORDER BY id ... LIMIT`` query that completes before we
        yield, so no long-lived cursor spans the stream and a session reset
        between pages is harmless. Memory stays bounded to one page.

        Falls back to the repository's ``iter_rows``/``find_all`` for fakes and
        repos without a real SQLAlchemy session + ``id``-keyed model (unit tests).
        """
        if self._supports_keyset_paging():
            return self._keyset_paged_rows(EXPORT_CHUNK_SIZE)
        iter_rows = getattr(self._repository, "iter_rows", None)
        if callable(iter_rows):
            return iter_rows(EXPORT_CHUNK_SIZE)
        return self._repository.find_all()

    def _supports_keyset_paging(self) -> bool:
        """True when this exchanger can page by a real, ordered ``id`` column.

        Requires a SQLAlchemy session (``query``) and a class-level ``id``
        attribute on the model (every ``BaseModel`` has a UUID PK). In-memory
        fakes have neither, so they keep the legacy ``iter_rows``/``find_all``
        path.
        """
        return hasattr(self._session, "query") and hasattr(self._model_class, "id")

    def _keyset_paged_rows(self, page_size: int) -> Iterator[Any]:
        """Yield every row, paging by ascending primary key (keyset pagination).

        Each page is a fresh, self-contained query (``WHERE id > :last ORDER BY
        id LIMIT page_size``), so it never holds an open server-side cursor
        across a yield. Peak memory is one page of rows.
        """
        order_column = getattr(self._model_class, "id")
        last_id = None
        while True:
            query = self._session.query(self._model_class).order_by(order_column)
            if last_id is not None:
                query = query.filter(order_column > last_id)
            page = query.limit(page_size).all()
            if not page:
                return
            for row in page:
                yield row
            last_id = page[-1].id

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
            elif isinstance(value, Enum):
                value = value.value
            result[field_name] = value
        for fk_field, resolver in self._fk_natural_key_map.items():
            result[fk_field] = resolver(row)
        return result

    # ── import ───────────────────────────────────────────────────────────

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        rows = validate_envelope(payload, self.entity_key)
        return self._apply_rows(rows, mode=mode, dry_run=dry_run)

    def import_ndjson(
        self,
        lines: Iterable[str],
        *,
        mode: str,
        dry_run: bool,
        chunk_size: int = EXPORT_CHUNK_SIZE,
    ) -> ImportResult:
        """Stream-import an NDJSON artefact (header line + one row per line).

        Validates the header against this entity, then applies rows in
        ``chunk_size`` batches — each batch flushed before the next is parsed —
        so import is bounded-memory and never builds the full row list. A
        malformed line is reported WITH its 1-based line number via
        :func:`iter_ndjson_rows`, never silently skipped.
        """
        line_iterator = iter(lines)
        validate_ndjson_header(line_iterator, self.entity_key)
        result = ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)
        try:
            if mode == MODE_REPLACE_ALL and not dry_run:
                self._repository.delete_all()
            with profiling.span(profiling.SPAN_DESERIALISE):
                row_stream = iter_ndjson_rows(line_iterator)
                self._apply_row_stream(
                    row_stream, result, dry_run=dry_run, chunk_size=chunk_size
                )
        except Exception:
            self._session.rollback()
            raise
        if dry_run:
            self._session.rollback()
        else:
            self._session.commit()
        return result

    def _apply_rows(
        self, rows: List[dict], *, mode: str, dry_run: bool
    ) -> ImportResult:
        result = ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)
        # Dry-run never mutates: it probes (find existing) to project counts but
        # writes nothing, so it is side-effect-free even for a non-transactional
        # repository. A real session is also rolled back below for safety.
        try:
            if mode == MODE_REPLACE_ALL and not dry_run:
                self._repository.delete_all()
            with profiling.span(profiling.SPAN_DESERIALISE):
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

    def _apply_row_stream(
        self,
        rows: Iterable[dict],
        result: ImportResult,
        *,
        dry_run: bool,
        chunk_size: int,
    ) -> None:
        """Apply a streamed row iterable in ``chunk_size`` flushed batches."""
        flush = getattr(self._session, "flush", None)
        pending = 0
        for index, row in enumerate(rows):
            self._import_row(row, index, result, dry_run=dry_run)
            pending += 1
            if pending >= chunk_size and not dry_run and callable(flush):
                flush()
                pending = 0

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

    # ── bulk seed (load-test data generator, S89 Slice 2) ─────────────────

    def bulk_seed(
        self,
        count: int,
        *,
        reset: bool = False,
        batch_size: int = SEED_BATCH_SIZE,
    ) -> BulkSeedResult:
        """Generate ``count`` deterministic load-test rows through the repository.

        Idempotent: a row whose natural key is ``loadtest-<entity>-<i>`` already
        present is skipped, not duplicated. ``reset`` first drops every row whose
        natural key carries the :data:`LOADTEST_SLUG_PREFIX` (never real/demo
        data). Rows are inserted in ``batch_size`` chunks, each its own flush +
        commit, so a 100k seed is never a single giant transaction.

        Entities whose required FKs cannot be synthesised generically override
        :meth:`_seed_row` (and, if needed, the FK prerequisite) — this base
        version fills the natural key plus the declared public fields with
        deterministic placeholders, which is enough for a flat catalog row.
        """
        result = BulkSeedResult(entity=self.entity_key)
        if reset:
            result.deleted = self._reset_loadtest_rows()
            self._session.commit()

        existing_keys = self._existing_loadtest_keys()
        bulk_add = getattr(self._repository, "bulk_add", None)
        pending: List[Any] = []
        for index in range(count):
            natural_value = self._loadtest_natural_key(index)
            if natural_value in existing_keys:
                result.skipped += 1
                continue
            instance = self._build_instance(self._seed_row(index, natural_value))
            pending.append(instance)
            result.created += 1
            if len(pending) >= batch_size:
                self._flush_seed_batch(pending, bulk_add)
                pending = []
        if pending:
            self._flush_seed_batch(pending, bulk_add)
        return result

    def _flush_seed_batch(self, instances: List[Any], bulk_add: Any) -> None:
        """Insert one seed batch through the repo bulk API, then commit it.

        Each batch is its own committed transaction so a large seed is never a
        single giant transaction (the spec's TDD assertion). Falls back to
        per-row ``add`` for repositories without a bulk API.
        """
        if callable(bulk_add):
            bulk_add(instances)
        else:
            for instance in instances:
                self._repository.add(instance)
        self._session.commit()

    def _seed_row(self, index: int, natural_value: str) -> dict:
        """Build one synthetic row dict (natural key + placeholder public fields).

        Override in a subclass when an entity needs valid FKs or typed values;
        the base produces a flat row keyed by the natural key with string
        placeholders for the remaining public fields.
        """
        row = {self.natural_key: natural_value}
        for field_name in self._public_fields:
            if field_name == self.natural_key or field_name in self.secret_fields:
                continue
            row.setdefault(field_name, f"{natural_value}-{field_name}")
        return row

    def _loadtest_natural_key(self, index: int) -> str:
        return f"{LOADTEST_SLUG_PREFIX}{self.entity_key}-{index}"

    def _existing_loadtest_keys(self) -> set:
        """Return the set of already-present load-test natural keys (for idempotency)."""
        find_by_prefix = getattr(
            self._repository, "find_natural_keys_with_prefix", None
        )
        if callable(find_by_prefix):
            return set(find_by_prefix(LOADTEST_SLUG_PREFIX))
        keys = set()
        for row in self._row_stream():
            value = getattr(row, self.natural_key, None)
            if isinstance(value, str) and value.startswith(LOADTEST_SLUG_PREFIX):
                keys.add(value)
        return keys

    def _reset_loadtest_rows(self) -> int:
        """Delete every load-test row (matched by the slug prefix). Returns count."""
        delete_by_prefix = getattr(
            self._repository, "delete_natural_keys_with_prefix", None
        )
        if callable(delete_by_prefix):
            return delete_by_prefix(LOADTEST_SLUG_PREFIX)
        deleted = 0
        for row in list(self._row_stream()):
            value = getattr(row, self.natural_key, None)
            if isinstance(value, str) and value.startswith(LOADTEST_SLUG_PREFIX):
                self._session.delete(row)
                deleted += 1
        return deleted
