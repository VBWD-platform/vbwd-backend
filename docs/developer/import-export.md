# Import / Export (Unified Data Exchange) — developer guide

How the platform's import/export works and **how a plugin adds its own entities** to it. Sprint S46. For the architectural overview see `docs/architecture/data-exchange.md`; this guide is the hands-on extension reference with worked examples from the **cms** plugin and the **core** exchangers.

> **Scope:** entity **data** only. Plugin **configuration** is deliberately NOT exchangeable (config blobs hold provider/OAuth secrets, Stripe keys, the GHRM key path). Never route config through this subsystem.

## The one contract: `EntityExchanger`

Everything importable/exportable — core entities and plugin entities alike — implements one port: `vbwd/services/data_exchange/port.py`.

```python
class EntityExchanger(ABC):
    entity_key: str            # stable id, e.g. "currencies", "cms_posts"
    label: str                 # human label for the UI
    cluster: str               # UI grouping: "sales" | "settings" | any string (e.g. "content")
    natural_key: str           # the portable identity field, e.g. "code"/"slug"/"email"
    supports_export: bool = True
    supports_import: bool = True
    supported_formats: frozenset = frozenset({"json"})   # add "csv" for flat entities
    secret_fields: frozenset = frozenset()               # never serialised, any role
    pii_fields: frozenset = frozenset()                  # redacted unless include_pii

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope: ...
    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult: ...

    # default permission names — override to reuse your plugin's existing perms
    @property
    def export_permission(self) -> str:      return f"{self.entity_key}.export"
    @property
    def import_permission(self) -> str:      return f"{self.entity_key}.import"
    @property
    def pii_export_permission(self) -> str:  return f"{self.entity_key}.export.pii"
```

Carriers (same module): `ExportSelector(ids?, filters?, all)`, `Envelope(entity_key, rows: list[dict])`, `ImportResult(entity, mode, dry_run, created, updated, skipped, errors[])`.

**Rules the contract enforces:**
- `export()` returns instance-independent rows: **strip UUIDs**, **strip `secret_fields`**, **redact `pii_fields`** unless `include_pii`, and serialise FKs as the **referent's natural key** (not its UUID).
- `import_()` upserts by `natural_key`. **Export-only** entities raise `UnsupportedOperationError` from `import_` (Liskov) — don't silently fail.
- `dry_run=True` computes the counts then **rolls back** (writes nothing).

## The fast path: `BaseModelExchanger`

For the common "one SQLAlchemy model + one repository, upsert by natural key" case, subclass nothing — just construct `BaseModelExchanger` (`vbwd/services/data_exchange/base_model_exchanger.py`). It does the stripping/redaction/FK-mapping/row-cap/CSV-flatten for you:

```python
from vbwd.services.data_exchange.base_model_exchanger import BaseModelExchanger

currencies = BaseModelExchanger(
    entity_key="currencies",
    label="Currencies",
    cluster="settings",
    natural_key="code",
    model_class=Currency,
    repository=currency_repo,          # any object with the repo methods (see adapter below)
    session=db.session,
    public_fields=["code", "name", "symbol", "decimal_places",
                   "exchange_rate", "is_active", "is_default"],
    supported_formats=frozenset({"json", "csv"}),
)
```

Need custom shaping (nested objects, binaries, delegating to an existing service)? Subclass `EntityExchanger` directly and implement `export`/`import_` (see the cms `CmsPostsExchanger`/`CmsImagesExchanger` below).

### The repository adapter (ISP)

`BaseModelExchanger` expects a narrow repo interface (`find_all`, `find_by_natural_key`, `add`, `delete_all`). Rather than widen your real repositories, wrap a session in a tiny adapter — every exchanger module ships its own copy (core's `core_exchangers.py` and cms's `cms_exchangers.py` each carry one; sharing it would require a cross-plugin home that violates the boundary rules):

```python
class _SessionModelRepository:
    def __init__(self, session, model_class, natural_key):
        self._session, self._model, self._natural_key = session, model_class, natural_key
    def find_all(self):
        return self._session.query(self._model).all()
    def find_by_natural_key(self, value):
        return self._session.query(self._model).filter(
            getattr(self._model, self._natural_key) == value).first()
    def add(self, instance):  self._session.add(instance)
    def delete_all(self):     self._session.query(self._model).delete()
```

## Registering from a plugin (the only wiring you write)

Core never imports `plugins.*` (enforced by `tests/unit/test_core_agnosticism.py`). A plugin registers its exchangers into the shared singleton **at `on_enable()`** via DI. Pattern (the cms plugin, `plugins/cms/__init__.py`):

```python
from vbwd.services.data_exchange.registry import data_exchange_registry

def register_cms_exchangers(session, *, file_storage) -> None:
    for exchanger in build_cms_exchangers(session, file_storage=file_storage):
        data_exchange_registry.register(exchanger)   # idempotent: replaces by entity_key

class CmsPlugin(BasePlugin):
    def on_enable(self):
        ...
        register_cms_exchangers(db.session, file_storage=storage)
```

That's it. The entity now appears in the manifest, the Settings → Import/Export page, the per-list controls, and the CLI — and its permissions are auto-added to the Access Level form.

`data_exchange_registry` API: `register(exchanger)` / `unregister(key)` / `clear()` / `get(key)` / `all()` / `manifest_for(user)`.

## Permissions

- **Mint nothing if you can reuse.** Settings-cluster exchangers reuse the global `settings.view` (export) / `settings.manage` (import). Plugin exchangers should **override `export_permission`/`import_permission` to the plugin's existing perms** (cms reuses `cms.pages.view/manage`, `cms.images.*`, etc.) rather than creating `<key>.export`/`.import`.
- Sales-cluster core entities use the per-entity `<key>.export` / `.import` / `.export.pii`, auto-derived from the registry into `collect_permission_catalog()` and shown in the Access Level form.
- **Superadmin** bypasses all checks (incl. `replace_all` and PII).
- Whatever permission names your exchanger reports are enforced by the routes — so a user who can't manage your entity can't import it.

## Envelope, modes, formats

The route/CLI layer wraps your `Envelope.rows` in the VBWD-standard envelope (`vbwd/services/data_exchange/envelope.py`):

```json
{ "vbwd_export": "currencies", "version": 1, "exported_at": "…", "instance": "main",
  "format": "json", "currencies": [ { "code": "EUR", … } ] }
```

- **JSON** always. **CSV** only if you list `"csv"` in `supported_formats` (flat entities; no nested objects).
- **ZIP bundle** — multiple entities in one archive (`manifest.json` + per-entity files + `assets/` for binaries). Zip-bomb + path-traversal guarded.
- **Modes:** `upsert` (default), `replace_all` (drop-then-import; superadmin-only via the API), `dry_run` (preview counts, no write).

## REST API & CLI

Routes (`/api/v1/admin/data-exchange/`, `require_admin`): `GET /manifest`, `POST /<key>/export`, `POST /<key>/import`, `POST /export` (bundle), `POST /import` (bundle). PII redacted unless the caller holds the PII perm; `replace_all` requires superadmin.

CLI (operator tool, runs in app context so all exchangers are registered):
```bash
flask data-exchange list
flask data-exchange export currencies --all -o currencies.json
flask data-exchange export users --ids <id1>,<id2> --include-pii
flask data-exchange import currencies currencies.json --mode upsert --dry-run
```

## Worked example A — core `currencies` (BaseModelExchanger)

See `vbwd/services/data_exchange/core_exchangers.py`: a `BaseModelExchanger` over `Currency` (natural key `code`, json+csv, no secrets/PII), registered by `register_core_exchangers(db.session)` from the app factory. The simplest possible exchanger — copy this shape for any flat model.

## Worked example B — cms `cms_posts` (custom `EntityExchanger`, delegates to a service)

`plugins/cms/src/services/data_exchange/cms_exchangers.py` `CmsPostsExchanger` does NOT use `BaseModelExchanger` — it **delegates to the existing `post_import_export_service`** so post serialization (including the S55 `content_blocks` + `page_assignments`) lives in exactly one place (DRY). It declares `cluster = "content"`, `natural_key = "slug"`, and overrides `export_permission` to `cms.pages.view`. Pattern to copy when an entity already has a serializer or needs nested shaping. (Binaries: `CmsImagesExchanger` emits the image bytes base64 in the JSON envelope and writes them back through the gallery `IFileStorage`, supporting both the JSON route and a ZIP bundle.)

## Testing your exchanger (TDD)

- **Unit:** register your exchanger into `data_exchange_registry` in the test (and `clear()` in teardown); assert it appears in `manifest_for` with the right cluster + `can_*` flags; export strips secrets / redacts PII without the perm; export-only raises `UnsupportedOperationError`.
- **Integration (`db`):** round-trip by natural key — export → wipe → import → equal; `dry_run` writes nothing; `replace_all` gated to superadmin. Seed via services/repos (no raw SQL).
- Keep `tests/unit/test_core_agnosticism.py` + `test_core_no_domain_vocabulary.py` green — exchangers import only `vbwd.services.data_exchange.*`; all `plugins.*` wiring is on the plugin side.

## Checklist for a new plugin exchanger

1. Pick `entity_key`, `cluster`, `natural_key`; decide `secret_fields` / `pii_fields` / `supported_formats` / export-only.
2. `BaseModelExchanger` (flat model) **or** subclass `EntityExchanger` (nested/binary/delegating).
3. Override `export_permission`/`import_permission` to reuse the plugin's existing perms.
4. Add a `register_<plugin>_exchangers(session, …)` and call it from `on_enable()` (idempotent).
5. Tests first: manifest + round-trip + secret/PII + export-only.
6. Gate: `bin/pre-commit-check.sh --plugin <name> --full` + the two core oracles green.
