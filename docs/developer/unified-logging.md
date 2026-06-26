# Unified Logging (vbwd backend)

**Status:** shipped in Sprint 58.5 (decision D9). Lives in `vbwd/services/logging/`, installed at app boot by `vbwd/app.py::_install_unified_logging`.

Every log line and every domain event is routed to a predictable file under the
FilesystemManager's `logs` namespace (`${VBWD_VAR_DIR:-/app/var}/logs/`), as
machine-readable **JSON lines**, with secret **redaction** and size **rotation** —
and **logging can never crash the app**.

---

## TL;DR — what you write

Nothing special. Use the standard library logger, named by module:

```python
import logging

logger = logging.getLogger(__name__)   # e.g. "plugins.cms.src.services.foo"

logger.info("page published", extra={"vbwd_extra": {"slug": slug, "post_id": pid}})
logger.warning("falling back to default style")
logger.error("checkout failed: %s", err)
logger.exception("unexpected")          # ERROR + traceback
```

That's it. The router figures out **which file** the line belongs in from the
logger name and the level. No per-plugin handler wiring, no file paths in your
code. 84 existing modules already work this way unchanged.

---

## Where lines land

```
${VBWD_VAR_DIR}/logs/
├── core/                       # the vbwd.* logger namespace (and any non-plugin logger)
│   ├── error.log     ERROR / CRITICAL
│   ├── warnings.log  WARNING
│   ├── info.log      INFO
│   └── events.log    every EventBus event (global audit trail)
└── <plugin>/                   # cms, ghrm, email, booking, tarot, …
    ├── error.log     ERROR / CRITICAL from plugins.<plugin>.*
    └── events.log    events attributable to that plugin
```

### How `scope` is derived
- Logger name `plugins.<id>.…`  →  scope **`<id>`** (the plugin id).
- Logger name `vbwd.…`, the root logger, or any third-party library  →  scope **`core`**.

So `getLogger(__name__)` inside `plugins/cms/...` automatically scopes to `cms`;
inside `vbwd/...` it scopes to `core`. **Always use `__name__`** — never
`getLogger("some-literal")`, or scope detection can't work.

### How `stream` is derived (by level)
| level | file |
|---|---|
| ERROR, CRITICAL | `error.log` |
| WARNING | `warnings.log` |
| INFO | `info.log` |
| DEBUG and below | **dropped** (not written to disk) |

### The per-scope allowlist (and "folding")
By default each scope may only write a subset of streams:
- **core** → `{error, warnings, info}`
- **each plugin** → `{error}` only

A record whose `(scope, stream)` is **not** allowed is **folded into the `core`
file for that stream** — but the JSON line keeps the original `scope` and
`logger`, so attribution survives. Concretely:

- a plugin `logger.error(...)` → `logs/<plugin>/error.log`
- a plugin `logger.warning(...)` → `logs/core/warnings.log` (with `"scope":"<plugin>"`)
- a plugin `logger.info(...)` → `logs/core/info.log` (with `"scope":"<plugin>"`)

This keeps per-plugin directories lean (just `error.log` + `events.log`) while
still capturing everything. You can change the allowlist (see Configuration).

---

## Line format

One JSON object per line (newline-delimited / JSONL):

```json
{"ts":1749312000.12,"level":"ERROR","scope":"cms","stream":"error","logger":"plugins.cms.src.services.contact_form_service","msg":"send failed","slug":"contact"}
```

Fields: `ts` (epoch float), `level`, `scope`, `stream`, `logger`, `msg`, plus any
**redacted** structured context you attached.

### Attaching structured context
Prefer a single `vbwd_extra` dict (it's merged into the line and redacted):

```python
logger.info("token debited", extra={"vbwd_extra": {"user_id": uid, "amount": n}})
```

Plain `extra={...}` attributes also work, but `vbwd_extra` is the convention and
avoids clashing with reserved `LogRecord` fields.

---

## The events stream (audit trail)

Every `EventBus.publish(name, payload)` is mirrored to **`logs/core/events.log`**
automatically (the `EventLogSubscriber` is subscribed to all events at boot).
This is the global audit trail — it is the stream whose absence hid the
"contact-form event fired but nothing handled it" bug.

```json
{"ts":1749312000.5,"event":"contact_form.received","payload":{"recipient_email":"a@b.c","fields":[...]}}
```

**Per-plugin `logs/<plugin>/events.log`** is best-effort. The EventBus exposes no
publisher identity, so an event is attributed to a plugin **only** when there's a
reliable signal:
- a namespaced event name `plugins.<id>.…` → `<id>`, or
- an explicit `_origin` / `origin_plugin` key in the payload.

Otherwise it stays in `core/events.log` only (no stack-walking is done). If you
want your plugin's events in its own `events.log`, namespace the event name or add
`"_origin": "<your-plugin-id>"` to the payload.

---

## Secret redaction (always on)

Before any line is written, keys whose **lower-cased name contains** any of these
are masked to `"***"` (recursively, through nested dicts/lists):

`password`, `passwd`, `secret`, `token`, `authorization`, `api_key`, `apikey`,
`private_key`, `smtp_password`, `client_secret`, `access_token`

So `logger.info("...", extra={"vbwd_extra": {"api_key": k}})` and an event payload
carrying `{"client_secret": ...}` are both masked on disk. **Still, never log a
raw secret deliberately** — redaction is a safety net, not a license. The actual
secret *files* live in the `secrets/` filesystem namespace (D4) and are never
logged.

---

## Rotation & configuration

Each stream file rotates by **size**: at `max_bytes` it rolls
`error.log → error.log.1 → … → error.log.<backups>` (oldest dropped) under an
exclusive lock, so concurrent gunicorn workers never double-rotate.

Defaults: **10 MiB per file, 5 backups**. Override via Flask config or env:

| setting | Flask config | env | default |
|---|---|---|---|
| max bytes/file | `LOG_MAX_BYTES` | `VBWD_LOG_MAX_BYTES` | `10485760` |
| backup segments | `LOG_BACKUPS` | `VBWD_LOG_BACKUPS` | `5` |

For deeper customisation (e.g. give a noisy plugin its own `warnings`/`info`
files, or raise the captured level), construct a `LoggingConfig`:

```python
from vbwd.services.logging import LoggingConfig
LoggingConfig(
    scope_streams={"cms": {"error", "warnings", "info"}},  # cms keeps its own warnings/info
    max_bytes=50 * 1024 * 1024,
    backups=10,
)
```

---

## Behaviour in tests

The disk router is **not** attached when `app.config["TESTING"]` is set — pytest
is never polluted and never writes `/app/var/logs`; the console handler stays. To
unit-test logging itself, drive `VbwdLogRouter` / `EventLogSubscriber` **directly**
with a `tmp_path` `LocalFilesystemManager` or an `InMemoryFilesystemManager` (see
`tests/unit/services/logging/`). Don't rely on the guarded boot path in tests.

---

## Resilience

`VbwdLogRouter.emit()` wraps the entire write path in try/except and degrades to
**stderr** on any failure; the event subscriber is likewise defensive. A broken or
unwritable `logs` root will **never** raise into your request path. Boot wiring is
best-effort too — the app starts even if logging can't initialise.

---

## Do / Don't

**Do**
- `logger = logging.getLogger(__name__)` at module top; log through it.
- Use `logger.error/exception` for failures (so they land in `error.log`), not `print`.
- Put structured context in `extra={"vbwd_extra": {...}}`.
- Namespace events (`plugins.<id>.…`) or set `_origin` if you want per-plugin `events.log`.

**Don't**
- ❌ `print(...)` for errors/diagnostics — it bypasses the structured logs (and redaction). Several legacy sites (e.g. `plugins/tarot/...` `print(f"LLM error: {e}")`) should be `logger.exception(...)`.
- ❌ Add your own `FileHandler` / `RotatingFileHandler` / `logging.basicConfig(...)` / hardcoded log paths. That bypasses scope routing, redaction, rotation, and confinement. (The legacy `plugins/cms-ai` logger does this — slated to move onto the router in 58.6.)
- ❌ `getLogger("literal-name")` — breaks scope derivation; use `__name__`.
- ❌ Open files under `var/logs/` directly — go through the FilesystemManager `logs` namespace if you ever need raw access.

---

## Centralized read — the admin API (Sprint 106, S106)

In production the box is reachable only over **SFTP** (no shell), so you cannot
`tail`/`grep` a log there. The `LogReaderService`
(`vbwd/services/logging/reader.py`) is the read side of the layer: it parses,
merges, time-orders, and filters the same on-disk JSON-lines back into a single
newest-first view, exposed over an **admin API** (and an fe-admin **Logs** view).

It is **scope-agnostic** — it discovers whatever scope directories exist under
`logs/` and never names a plugin — and **capped** so a query can never scan an
unbounded amount of disk; whatever it drops is surfaced (`truncated`,
`bytes_scanned`), never silent.

All endpoints require `@require_auth` + `@require_permission("logs.read")`:

| endpoint | returns |
|---|---|
| `GET /api/v1/admin/logs/scopes` | `{scopes, streams}` — feeds the filter UI |
| `GET /api/v1/admin/logs` | `{records, next_cursor, truncated, bytes_scanned, segments_scanned, malformed_skipped}` |
| `GET /api/v1/admin/logs/download?scope=&stream=` | one stream as chronological `application/x-ndjson` |
| `GET /api/v1/admin/logs/stream?scope=&stream=` | **SSE** live tail (`text/event-stream`) |

Query params (all optional): `scope` (repeatable / comma-separated), `stream`,
`level` (min floor), `minutes` (window) or `since`/`until` (epoch seconds;
`since=0` = all history), `contains` (case-insensitive substring), `limit`,
`cursor` (pass back `next_cursor` to page). Records are newest-first; the
events stream (level-less audit) is never dropped by a `level` floor.

Scope/stream are validated against the live directory listing, so an unknown or
`../` value is a **400**, never a path escape.

### SSE buffering — read this before debugging "the tail only updates on refresh"

The `/stream` response sets `X-Accel-Buffering: no` + `Cache-Control: no-cache`,
but a reverse proxy in front (e.g. the Hestia front nginx) can still buffer the
event-stream. **`proxy_buffering off` must be set at every hop**, or the tail
flushes only on disconnect. Diagnose with `curl -N <url>` — zero bytes until you
^C means a hop is buffering.

### Read caps — `var/core/logging.json` (ops override, optional)

Code defaults are the fallback ([`LogReaderConfig`]); a host-mounted
`${VBWD_VAR_DIR}/core/logging.json` overrides them without a rebuild:

```json
{
  "max_lines_per_request": 1000,
  "max_bytes_scanned": 26214400,
  "default_window_minutes": 60,
  "tail_backfill_lines": 50
}
```

---

## Ship-out to an external aggregator (Sprint 106, Phase 2)

The same records can be **shipped** to an external log aggregator (Loki, Sentry,
…) through an agnostic seam. Core names no vendor and **ships nothing by
default** — with no shipper registered the whole mechanism is inert.

**The seam** (`vbwd/services/logging/shipping/`):

* `LogShipper` (port) — `name` + `ship(records) -> ShipResult`. A shipper gets a
  batch of the same redacted record dicts and forwards them; it returns a result
  rather than raising.
* `log_shipper_registry` — module singleton plugins register a shipper into on
  `on_enable` (unregister on `on_disable`), keyed by name.
* `log_ship_dispatcher` — the router feeds every emitted record to it via a
  `ship_hook` (a cheap, lock-guarded append into a bounded ring buffer; drops the
  oldest + counts when full, so a burst never blocks the app or grows memory).
  Inert until a shipper registers.
* A TESTING-guarded background scheduler (mirroring the webhook delivery
  scheduler) drains a batch each tick and fans it to every **ready** shipper,
  with per-shipper **exponential backoff + auto-disable** so one failing backend
  is isolated. When all shippers are backing off the batch is held (buffered) up
  to capacity. **Shipping is best-effort — the on-disk logs are the durable
  source of truth.**

**Config** lives in the `shipping` block of `var/core/logging.json` (defaults in
code):

```json
{
  "shipping": {
    "enabled": true,
    "flush_interval_seconds": 10,
    "max_batch": 500,
    "buffer_capacity": 10000,
    "min_level": "info",
    "backoff_base_seconds": 30,
    "backoff_cap_seconds": 21600,
    "auto_disable_threshold": 5
  }
}
```

**Writing a shipper plugin** — register on enable, unregister on disable:

```python
from vbwd.services.logging.shipping import (
    LogShipper, ShipResult, log_shipper_registry, log_ship_dispatcher,
)

class MyShipper(LogShipper):
    @property
    def name(self): return "myaggregator"
    def ship(self, records):
        try:
            ...  # POST the batch
            return ShipResult.success()
        except Exception as e:
            return ShipResult.failure(str(e))   # backoff, never raise

# in the plugin:
def on_enable(self):
    log_shipper_registry.register(MyShipper())
    log_ship_dispatcher.reset_shipper("myaggregator")
def on_disable(self):
    log_shipper_registry.unregister("myaggregator")
```

**The Loki shipper** (`plugins/log_shipper_loki/`) is the reference
implementation: it groups records into Loki streams labelled by
`app`/`scope`/`level`/`stream` (+ static `extra_labels`), each line the full
JSON record, and POSTs to `<endpoint_url>/loki/api/v1/push` with optional
basic-auth + `X-Scope-OrgID`. Off by default; set `endpoint_url` (+ credentials)
in the plugin config.

---

## Reading the logs (raw, on-disk)

If you do have shell/SFTP access, JSONL is `grep`/`jq`-friendly:

```bash
# all cms errors, newest formatting
jq -c 'select(.scope=="cms")' /app/var/logs/cms/error.log

# every contact-form event today
jq -c 'select(.event=="contact_form.received")' /app/var/logs/core/events.log

# warnings folded from any plugin
jq -c 'select(.scope!="core")' /app/var/logs/core/warnings.log
```

---

## Internals (for maintainers)

| file | role |
|---|---|
| `vbwd/services/logging/router.py` | `VbwdLogRouter` — the root handler (scope+stream routing, JSON, rotation) |
| `vbwd/services/logging/subscriber.py` | `EventLogSubscriber` — mirrors EventBus publishes to `events.log` |
| `vbwd/services/logging/redaction.py` | `redact()` — recursive secret masking |
| `vbwd/services/logging/config.py` | `LoggingConfig` — allowlist, level band, rotation limits |
| `vbwd/services/logging/reader.py` | `LogReaderService` — the centralized read side (parse/merge/filter/tail) |
| `vbwd/routes/admin/logs.py` | `admin_logs_bp` — the `logs.read`-gated admin API |
| `vbwd/services/logging/shipping/` | `LogShipper` port + registry + dispatcher/scheduler (ship-out seam) |
| `plugins/log_shipper_loki/` | reference shipper plugin — pushes records to Grafana Loki |
| `vbwd/app.py::_install_unified_logging` | TESTING-guarded boot wiring |

All writes go through the FilesystemManager `logs` namespace
(`vbwd/services/filesystem/`, Sprint 58.0) — so they inherit path confinement,
the append/rotation policy, and the single var-root.
