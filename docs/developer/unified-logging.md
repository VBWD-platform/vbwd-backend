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
└── <plugin>/                   # cms, ghrm, email, booking, taro, …
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
- ❌ `print(...)` for errors/diagnostics — it bypasses the structured logs (and redaction). Several legacy sites (e.g. `plugins/taro/...` `print(f"LLM error: {e}")`) should be `logger.exception(...)`.
- ❌ Add your own `FileHandler` / `RotatingFileHandler` / `logging.basicConfig(...)` / hardcoded log paths. That bypasses scope routing, redaction, rotation, and confinement. (The legacy `plugins/cms-ai` logger does this — slated to move onto the router in 58.6.)
- ❌ `getLogger("literal-name")` — breaks scope derivation; use `__name__`.
- ❌ Open files under `var/logs/` directly — go through the FilesystemManager `logs` namespace if you ever need raw access.

---

## Reading the logs

JSONL is `grep`/`jq`-friendly:

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
| `vbwd/app.py::_install_unified_logging` | TESTING-guarded boot wiring |

All writes go through the FilesystemManager `logs` namespace
(`vbwd/services/filesystem/`, Sprint 58.0) — so they inherit path confinement,
the append/rotation policy, and the single var-root.
