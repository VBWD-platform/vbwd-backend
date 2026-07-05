# vbwd-backend docs

- **[architecture/](architecture/)** — cross-cutting backend architecture references.
  - [Webhooks](architecture/webhooks.md) — inbound (provider) + outbound (subscriber) webhook systems, signing, delivery, retries, event catalog.
- **[developer/](developer/)** — per-plugin / per-integration developer guides
  (stripe, paypal, yookassa, cms, chat, ghrm, tarot, email, mailchimp, analytics,
  import-export, unified-logging, demoplugin, …).
  - [Packaging & pip installation](developer/packaging.md) — how core + every plugin build as PEP 517 packages, the `plugins.<name>` `package-dir` remap, the build-only decision, and `pip install git+…` commands.

See also the repo root `CLAUDE.md` for the high-level project overview and the
layered backend architecture (Routes → Services → Repositories → Models) and
the plugin system.
