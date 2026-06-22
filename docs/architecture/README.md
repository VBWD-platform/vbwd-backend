# Backend architecture docs

Cross-cutting backend architecture references. Per-plugin developer guides live
under [`../developer/`](../developer/).

| Doc | What it covers |
|---|---|
| [webhooks.md](webhooks.md) | The webhook system — **inbound** (per-payment-plugin, signature-verified provider webhooks + the hardened core `/webhooks/payment` admin mark-paid route) and **outbound** (the core `vbwd_webhook` / `vbwd_webhook_delivery` system: `/admin/webhooks` CRUD, the event-bus relay, HMAC signing, async retrying delivery, the subscribable event catalog, and subscriber-side verification snippets). |

> Add new cross-cutting architecture docs here and list them in the table above.
