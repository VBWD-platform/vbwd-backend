# Webhooks

vbwd has **two distinct webhook systems** that point in opposite directions.
Do not confuse them:

| System | Direction | Who calls whom | Lives in |
| --- | --- | --- | --- |
| **Inbound** | provider → vbwd | payment providers POST to us | payment plugins (+ a core admin tool) |
| **Outbound** | vbwd → subscriber | we POST to admin-registered URLs | core `vbwd/` (this document's focus) |

The outbound system is **generic, domain-agnostic core infrastructure**. It
relays whatever domain events are published on the core event bus to
subscriber URLs. It names no plugin and imports nothing from `plugins.*` (the
core-agnosticism oracle `tests/unit/test_core_agnosticism.py` AST-walks `vbwd/`
and would fail if it did).

---

## 1. Inbound webhooks (provider → vbwd)

These existed before the outbound system and are summarised here only so the
two are not confused.

### Per-provider plugin webhooks (signature-verified)

Real payment providers (Stripe, PayPal, YooKassa, and the regional providers)
POST event notifications to **their own plugin's** webhook route. Each plugin
owns its endpoint and verifies the provider's signature with the provider's
own scheme before acting (e.g. Stripe's `Stripe-Signature` HMAC, PayPal's
transmission-signature verification, YooKassa's IP/secret checks). These routes
live entirely in the respective payment plugins, never in core.

### The core `/api/v1/webhooks/payment` route — NOT a public webhook

`vbwd/routes/webhooks.py` exposes `POST /api/v1/webhooks/payment`. Despite the
legacy "webhook" name it is **not** a public provider webhook: it is the admin
"manually mark an invoice as paid" tool. It is hardened (S90) behind
`@require_auth` + `@require_permission("invoices.manage")` — previously it took
no auth and no signature, letting anyone forge a paid event. It emits a
`PaymentCapturedEvent` through the event dispatcher. `POST
/api/v1/webhooks/payment/test` is an unauthenticated reachability probe.

The outbound system below does **not** touch either of these routes.

---

## 2. Outbound webhooks (vbwd → subscriber) — the new system

An admin registers a **subscription**: a URL plus a list of event names it
wants. Whenever a matching domain event is published on the core event bus, we
enqueue a **delivery** and a background worker POSTs a signed JSON body to the
subscriber's URL, retrying with exponential backoff and auto-disabling
endpoints that keep failing.

### 2.1 Why two phases (enqueue then deliver)

The core event bus (`vbwd/events/bus.py`) is **synchronous**: `publish()` calls
every subscriber inline, inside the request that emitted the event. HTTP
delivery must never happen there — a slow or dead subscriber would block (or
fail) the user's request. So the design is two-phase:

1. **Enqueue** (synchronous, in the publishing request): find matching active
   subscriptions and insert one `pending` `WebhookDelivery` row per
   subscription. DB inserts only, no HTTP. Fast. Wrapped so a failure here can
   never break event emission.
2. **Deliver** (asynchronous, from a background scheduler): drain the due
   `pending` deliveries, POST each signed body, record the outcome, schedule
   retries or mark failed. The drain never raises.

---

## 3. Data model

Two pure-core tables, created by Alembic migration
`20260619_1000_outbound_webhooks` (revision id
`20260619_1000_outbound_webhooks`, parent `20260616_1600_rename_al_model`).
The migration has no plugin FK and resolves standalone.

### `vbwd_webhook` — subscriptions (`WebhookSubscription`)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | from `BaseModel` |
| `url` | String(2048) | http(s) only; validated on create/update |
| `secret` | String(128) | strong random secret generated on create if not supplied; used for HMAC signing |
| `event_types` | JSONB array | event-name strings; `["*"]` means "all events" |
| `is_active` | Boolean | persisted enable flag |
| `description` | Text, nullable | admin note |
| `last_triggered_at` | DateTime, nullable | updated on each enqueue |
| `consecutive_failure_count` | Integer | drives auto-disable |
| `created_at` / `updated_at` / `version` | from `BaseModel` | |

`status` is **derived**, not stored. `to_dict()` maps the persisted flags onto
the fe-admin `Webhook.status` union:

- `active` — `is_active` is true.
- `failed` — `is_active` is false **and** `consecutive_failure_count >= 5`
  (auto-disabled after repeated delivery failures; needs admin attention).
- `inactive` — `is_active` is false otherwise (admin toggled it off).

`to_dict()` returns exactly the fe `Webhook` shape:
`{id, url, events[], status, secret, description, created_at, last_triggered_at}`.

### `vbwd_webhook_delivery` — delivery attempts (`WebhookDelivery`)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `webhook_id` | UUID FK → `vbwd_webhook.id` | `ON DELETE CASCADE`, indexed |
| `event_type` | String(255) | the relayed event name |
| `event_payload` | JSONB | the event data dict |
| `status` | String(20) | `pending` \| `success` \| `failed` |
| `attempt_count` | Integer | incremented per POST attempt |
| `max_attempts` | Integer (default 5) | retries exhausted ⇒ `failed` |
| `next_attempt_at` | DateTime, nullable, indexed | when this delivery is next due |
| `response_code` | Integer, nullable | last HTTP status |
| `response_body` | Text, nullable | truncated to 2048 chars |
| `error` | Text, nullable | transport / non-2xx error text |
| `signature` | String(128), nullable | the signature sent |
| `delivered_at` | DateTime, nullable | set on success |

`to_dict()` returns the fe `WebhookDelivery` shape and extras:
`{id, webhook_id, event_type, status, response_code, response_body, error,
attempt_count, max_attempts, created_at, delivered_at}`.

---

## 4. Subscribable event catalog

A tiny process-level registry (`vbwd/webhooks/event_types.py`) of
`{value, label}` entries powers the admin event-type dropdown. It is
**advisory only**: delivery relays whatever event name is published, so an
unlisted event still reaches a `["*"]` subscriber.

Core seeds (`seed_core_webhook_event_types()`, called at app startup):

- `*` — All events
- `webhook.test` — the synthetic event the "Test" button emits
- `payment.captured`, `payment.authorized`, `payment.refunded`
- `payment.recurring_charge`, `payment.provider_cancelled`,
  `payment.recurring_failed`, `payment.invoice_failed`,
  `payment.provider_linked`
- `refund.reversed`

### Plugins can register their own event types

Without core naming any plugin, a plugin's `on_enable` may call:

```python
from vbwd.webhooks.event_types import register_webhook_event_type

register_webhook_event_type("shop.order.placed", "Shop order placed")
```

It is idempotent (last label wins) and thread-safe. The new entry appears in
the admin dropdown; the wildcard always sorts first.

---

## 5. Creating a subscription

### Admin UI

The fe-admin app has the **Webhooks** settings surface (`Webhooks.vue` /
`WebhookDetails.vue`, store `vue/src/stores/webhooks.ts`). Create a webhook
with a URL and a set of events; the generated `secret` is shown so the admin
can configure their receiver. The detail view lists recent deliveries.

### API

All endpoints are under `/api/v1/admin/webhooks`, gated
`@require_auth @require_permission("settings.manage")` — the same permission
the fe webhooks settings surface guards on.

| Verb & path | Purpose | Response |
| --- | --- | --- |
| `GET /api/v1/admin/webhooks?page&per_page&status` | list (paginated, optional status filter) | `{webhooks, total, page, per_page}` |
| `GET /api/v1/admin/webhooks/event-types` | subscribable catalog | `{event_types: [{value, label}]}` |
| `POST /api/v1/admin/webhooks` | create (`{url, events[], secret?, description?}`) | `201 {webhook}` |
| `GET /api/v1/admin/webhooks/<id>` | one subscription + recent deliveries | `{webhook: {..., delivery_history: [...]}}` |
| `PUT /api/v1/admin/webhooks/<id>` | update url / events / description | `{webhook}` |
| `DELETE /api/v1/admin/webhooks/<id>` | delete (cascades deliveries) | `{status: "deleted"}` |
| `POST /api/v1/admin/webhooks/<id>/toggle` | flip active state (re-enabling clears failure counter) | `{webhook}` |
| `POST /api/v1/admin/webhooks/<id>/test` | deliver a synthetic `webhook.test` now | `{delivery}` |

`url` must start with `http://` or `https://`; otherwise the create/update
returns `400`. If `secret` is omitted on create, a strong URL-safe secret is
generated (`secrets.token_urlsafe(32)`).

---

## 6. Delivery lifecycle

```
event published on bus
        │
        ▼  (wildcard relay, synchronous, in-request)
enqueue_for_event(name, data)
        │  insert one `pending` WebhookDelivery per matching active subscription
        │  next_attempt_at = now;  subscription.last_triggered_at = now
        ▼
[ background scheduler tick — every ~25s, or `flask webhooks deliver-due` ]
        │
        ▼  deliver_due(now, limit)
for each due delivery:                       # status=pending, attempts left, next_attempt_at <= now
        build signed JSON body → POST (5s timeout)
        ├── 2xx          → status=success, delivered_at=now, reset subscription failure counter
        └── non-2xx /    → attempt_count++
            timeout /        ├── attempts remain → status stays pending,
            conn error       │                     next_attempt_at = now + 30s * 2**attempt_count (capped 6h)
                             └── attempts exhausted → status=failed,
                                                       subscription.consecutive_failure_count++
                                                       if counter >= 5 → is_active=false (surfaced as 'failed')
```

### Retry / backoff

- `max_attempts` defaults to **5**.
- Backoff between attempts: `30s * 2 ** attempt_count`, capped at **6 hours**.
- Each tick processes deliveries whose `next_attempt_at <= now`, oldest-due
  first, so retries do not starve fresh deliveries.

### Auto-disable

- A delivery that exhausts `max_attempts` bumps the subscription's
  `consecutive_failure_count`.
- After **5 consecutive failed deliveries** the subscription is set
  `is_active = false`; `to_dict()` then surfaces `status = "failed"` so the
  admin sees it needs attention.
- A **successful** delivery resets `consecutive_failure_count` to 0.
- Toggling the subscription back on (or any explicit re-enable) clears the
  counter.

The drain **never raises**: a transport error, a non-2xx, or a failure loading
due rows is recorded/logged and the loop continues.

---

## 7. Background delivery (scheduler) and CLI

Delivery is driven by a background job started in the app factory
(`vbwd/app.py`), TESTING-guarded exactly like the booking/subscription
schedulers:

```python
if not app.config.get("TESTING"):
    start_webhook_delivery_scheduler(app)   # APScheduler, every 25s
```

Under pytest (`TESTING=true`) the scheduler never starts, so tests never fire
real HTTP. The same drain is available as a CLI for cron-driven delivery or
debugging:

```bash
flask webhooks deliver-due --limit 100
```

---

## 8. Signature scheme

Every outbound POST is signed and carries these headers:

| Header | Value |
| --- | --- |
| `Content-Type` | `application/json` |
| `X-VBWD-Signature` | `sha256=<hex HMAC-SHA256 of the raw body, keyed by the subscription secret>` |
| `X-VBWD-Event` | the event type (e.g. `payment.captured`) |
| `X-VBWD-Delivery-Id` | the `WebhookDelivery` id (idempotency key) |
| `X-VBWD-Timestamp` | unix seconds when the attempt was made |

The signature is computed over the **exact raw request body bytes** that are
transmitted. The body envelope is:

```json
{
  "id": "<delivery id>",
  "event_type": "payment.captured",
  "created_at": "2026-06-19T10:00:00",
  "data": { ...the event payload... }
}
```

(serialised with sorted keys so the signed bytes are stable).

### Verify on the subscriber side — Python

```python
import hashlib
import hmac

WEBHOOK_SECRET = "the secret shown in the admin UI"

def is_valid(raw_body: bytes, signature_header: str) -> bool:
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")

# Flask example — sign over request.get_data(), NOT a re-serialised dict:
# if not is_valid(request.get_data(), request.headers.get("X-VBWD-Signature")):
#     abort(401)
```

### Verify on the subscriber side — JavaScript (Node)

```js
const crypto = require('crypto');

const WEBHOOK_SECRET = 'the secret shown in the admin UI';

function isValid(rawBody, signatureHeader) {
  const expected =
    'sha256=' +
    crypto.createHmac('sha256', WEBHOOK_SECRET).update(rawBody).digest('hex');
  const a = Buffer.from(expected);
  const b = Buffer.from(signatureHeader || '');
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// Express: capture the RAW body so you sign the exact bytes that were sent:
//   app.use(express.raw({ type: 'application/json' }));
//   if (!isValid(req.body, req.get('X-VBWD-Signature'))) return res.sendStatus(401);
```

Always compute the HMAC over the **raw received bytes**, never over a
re-serialised object — re-serialisation can reorder keys or change whitespace
and break the comparison. Use a constant-time comparison
(`hmac.compare_digest` / `crypto.timingSafeEqual`).

---

## 9. Security notes

- **Always verify the signature** before trusting a payload. The secret is the
  only thing that proves the request came from vbwd.
- **HMAC, not bearer:** the secret is never transmitted; only the HMAC is.
- **Idempotency:** subscribers may receive the same `X-VBWD-Delivery-Id` more
  than once (a retry can fire after the subscriber already processed but
  returned non-2xx). Dedupe on the delivery id.
- **Use the timestamp** (`X-VBWD-Timestamp`) to reject very old deliveries if
  replay is a concern.
- **http vs https:** the system allows `http://` for local/dev targets but
  prefer `https://` in production; never send secrets to an untrusted URL.
- **Response bodies are truncated** to 2048 chars before storage so a chatty
  subscriber cannot bloat the deliveries table.

---

## 10. Source map

| Concern | File |
| --- | --- |
| Subscription model | `vbwd/models/webhook_subscription.py` |
| Delivery model | `vbwd/models/webhook_delivery.py` |
| Repositories | `vbwd/repositories/webhook_subscription_repository.py`, `vbwd/repositories/webhook_delivery_repository.py` |
| Service (CRUD, enqueue, deliver, backoff, auto-disable) | `vbwd/webhooks/outbound_service.py` |
| Signing | `vbwd/webhooks/signing.py` |
| Event-type registry | `vbwd/webhooks/event_types.py` |
| Bus relay + scheduler | `vbwd/webhooks/relay.py` |
| Admin routes | `vbwd/routes/admin/webhooks.py` |
| CLI drain | `vbwd/cli/webhooks.py` |
| Migration | `alembic/versions/20260619_1000_outbound_webhooks.py` |
| App wiring (seed + relay + scheduler) | `vbwd/app.py` |
| Inbound admin "mark paid" route | `vbwd/routes/webhooks.py` |
| fe-admin store / views | `vbwd-fe-admin/vue/src/stores/webhooks.ts`, `Webhooks.vue`, `WebhookDetails.vue` |
