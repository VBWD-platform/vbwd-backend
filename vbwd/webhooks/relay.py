"""Event-bus relay + delivery scheduler for outbound webhooks (core).

Wires the agnostic outbound webhook system into the running app:

* :func:`register_outbound_webhook_relay` subscribes a single callback to the
  EventBus *wildcard* (``subscribe_all``). For every published event it
  enqueues pending deliveries for the matching subscriptions. The enqueue is
  wrapped so a webhook failure never breaks event emission.
* :func:`start_webhook_delivery_scheduler` starts a background job that drains
  due deliveries (the synchronous bus never performs HTTP itself). The caller
  TESTING-guards this exactly like the other core/plugin schedulers so pytest
  never starts the job or fires real HTTP.

Neither function names any plugin — the relay forwards whatever events flow.
"""
from __future__ import annotations

import logging

from vbwd.extensions import db
from vbwd.repositories.webhook_delivery_repository import WebhookDeliveryRepository
from vbwd.repositories.webhook_subscription_repository import (
    WebhookSubscriptionRepository,
)
from vbwd.webhooks.outbound_service import OutboundWebhookService

logger = logging.getLogger(__name__)

# Default scheduler cadence — how often due deliveries are drained.
DELIVERY_INTERVAL_SECONDS = 25

# How many due deliveries to drain per scheduler tick.
DELIVERY_BATCH_LIMIT = 100


# Marker attribute set on a bus once a relay is subscribed, so re-creating the
# app (multiple ``create_app`` calls share the module-singleton bus, e.g. the
# whole test suite) never stacks duplicate relay callbacks on it.
_RELAY_MARKER = "_vbwd_outbound_webhook_relay_target_app"


def register_outbound_webhook_relay(app, event_bus) -> None:
    """Subscribe the wildcard relay that enqueues a delivery per event.

    Idempotent per bus: the relay is bound to the *current* app and replaces
    any previously bound app so a re-created app (a fresh ``create_app``) does
    not leave a stale relay firing into a dead app context. Only one relay
    callback is ever attached to a given bus.
    """
    # The single relay callback closes over a mutable holder so the target app
    # can be swapped without subscribing a second callback.
    holder = getattr(event_bus, _RELAY_MARKER, None)
    if holder is not None:
        holder["app"] = app
        return

    holder = {"app": app}

    def _relay(event_name: str, data: dict) -> None:
        target_app = holder["app"]
        try:
            with target_app.app_context():
                service = OutboundWebhookService(
                    subscription_repository=WebhookSubscriptionRepository(db.session),
                    delivery_repository=WebhookDeliveryRepository(db.session),
                )
                enqueued = service.enqueue_for_event(event_name, data or {})
                if enqueued:
                    logger.debug(
                        "[webhook] Enqueued %d deliveries for %s",
                        enqueued,
                        event_name,
                    )
        except Exception as relay_error:  # noqa: BLE001 — never break emission
            logger.warning(
                "[webhook] Relay failed for event %s: %s", event_name, relay_error
            )

    setattr(event_bus, _RELAY_MARKER, holder)
    event_bus.subscribe_all(_relay)
    logger.info("[webhook] Outbound relay subscribed to the event bus")


def run_webhook_delivery_job(app) -> None:
    """Scheduler tick: drain due deliveries inside an app context."""
    with app.app_context():
        service = OutboundWebhookService(
            subscription_repository=WebhookSubscriptionRepository(db.session),
            delivery_repository=WebhookDeliveryRepository(db.session),
        )
        attempted = service.deliver_due(limit=DELIVERY_BATCH_LIMIT)
        if attempted:
            logger.info("[webhook] Delivered/attempted %d due webhooks", attempted)


def start_webhook_delivery_scheduler(
    app, interval_seconds: int = DELIVERY_INTERVAL_SECONDS
):
    """Start the background drain job (caller must TESTING-guard)."""
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_webhook_delivery_job,
        "interval",
        seconds=interval_seconds,
        args=[app],
        id="webhook_delivery",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[webhook] Delivery scheduler started (interval=%ds)", interval_seconds)
    return scheduler
