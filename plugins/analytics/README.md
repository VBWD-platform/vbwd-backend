# Analytics Plugin

Dashboard analytics widget — provides active sessions count.

## Structure

```
plugins/analytics/
├── __init__.py          # AnalyticsPlugin class (discovery entry point)
├── config.json          # Config schema (field types, defaults, descriptions)
├── admin-config.json    # Admin UI layout (tabs, form fields)
├── README.md
├── src/
│   ├── __init__.py
│   └── routes.py        # Flask blueprint + API endpoints
└── tests/
    ├── __init__.py
    ├── conftest.py      # Test fixtures (app, client)
    ├── test_plugin.py   # Plugin lifecycle + functionality tests
    └── test_routes.py   # Route endpoint tests
```

## Plugin Lifecycle

### 1. Discovery

On app startup, `PluginManager.discover("plugins")` scans the `plugins/` package. It finds `AnalyticsPlugin` in `plugins/analytics/__init__.py` and auto-registers + initializes it.

**Important:** The plugin class **must** be defined in `__init__.py` (not re-exported from another module). The discovery check `obj.__module__ != full_module` rejects re-exported classes.

### 2. State Machine

```
DISCOVERED → REGISTERED → INITIALIZED → ENABLED ↔ DISABLED
```

- `DISCOVERED` — class instantiated
- `REGISTERED` — added to PluginManager registry
- `INITIALIZED` — `initialize(config)` called, plugin ready to enable
- `ENABLED` — `enable()` called, `on_enable()` hook fires, routes serve traffic
- `DISABLED` — `disable()` called, `on_disable()` hook fires, routes return 404

### 3. Persistence

Plugin state is persisted to `plugins/plugins.json` (shared across Gunicorn workers). This JSON file is the **source of truth** — not in-memory state.

On startup, `PluginManager.load_persisted_state()` reads the JSON and enables previously-enabled plugins.

### 4. Configuration

| File | Purpose |
|------|---------|
| `config.json` | Schema — defines available config fields (type, default, description) |
| `admin-config.json` | UI layout — defines tabs and form fields for the admin Settings page |
| `plugins/config.json` | Saved values — persisted config values set by the admin |

Config values are read at runtime via `config_store.get_config("analytics")`.

### 5. Routes

Blueprint registered at startup. Route handlers check enabled status via `config_store` before serving:

```
GET /api/v1/plugins/analytics/active-sessions  (requires auth + admin)
```

Returns `{"count": N, "source": "plugin"}` when enabled, `404` when disabled.

### 6. Admin API

These endpoints are provided by the core admin plugins API (`src/routes/admin/plugins.py`):

```
GET    /api/v1/admin/plugins/analytics          — plugin detail + config schema
PUT    /api/v1/admin/plugins/analytics/config    — save config values
POST   /api/v1/admin/plugins/analytics/enable    — enable plugin
POST   /api/v1/admin/plugins/analytics/disable   — disable plugin
```

## Running Tests

### Plugin tests only

```bash
cd vbwd-backend
docker compose run --rm test pytest plugins/analytics/tests/ -v
```

### Plugin tests as part of the full suite

```bash
cd vbwd-backend
docker compose run --rm test pytest tests/unit/ plugins/analytics/tests/ -v \
  --ignore=tests/unit/plugins/test_mock_payment_plugin.py
```

### Individual test files

```bash
# Lifecycle + functionality
docker compose run --rm test pytest plugins/analytics/tests/test_plugin.py -v

# Route endpoints
docker compose run --rm test pytest plugins/analytics/tests/test_routes.py -v
```

## Creating a New Plugin

Use this plugin as a template:

1. Create `plugins/<name>/__init__.py` with a class extending `BasePlugin`
2. Define `metadata` property (name, version, author, description)
3. Add `config.json` (schema) and `admin-config.json` (UI layout) if configurable
4. Add routes in `src/routes.py`, return the blueprint from `get_blueprint()`
5. Check `config_store.get_by_name("<name>")` in route handlers for enabled status
6. Add tests in `tests/` with a `conftest.py` providing `app`/`client` fixtures
7. The plugin is auto-discovered on next app restart — no manual registration needed

---

## Related

| | Repository |
|-|------------|
| 🛠 Frontend (admin) | [vbwd-fe-admin-plugin-analytics-widget](https://github.com/VBWD-platform/vbwd-fe-admin-plugin-analytics-widget) |

**Core:** [vbwd-backend](https://github.com/VBWD-platform/vbwd-backend)
