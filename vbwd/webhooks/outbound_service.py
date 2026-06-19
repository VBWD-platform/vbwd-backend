"""Outbound webhook delivery service (core, plugin-agnostic).

Relays domain events published on the core event bus to admin-registered
subscriber URLs. The flow is two-phase so that the HTTP work never happens
inside the request that emitted the event (the bus is synchronous):

1. ``enqueue_for_event`` — runs inside the publishing request. It finds the
   active endpoints matching the event name and inserts one *pending*
   :class:`WebhookDelivery` per endpoint (DB inserts only, no HTTP).
2. ``deliver_due`` — runs from the background scheduler. It drains due
   deliveries, POSTs the signed JSON body, records the outcome, and schedules
   exponential-backoff retries or marks the delivery failed.

The service names no plugin: it relays whatever event names are published.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Union
from uuid import UUID

from vbwd.models.webhook_delivery import (
    MAX_RESPONSE_BODY_CHARS,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SUCCESS,
    WebhookDelivery,
)
from vbwd.models.webhook_subscription import (
    AUTO_DISABLE_FAILURE_THRESHOLD,
    WebhookSubscription,
)
from vbwd.repositories.webhook_delivery_repository import WebhookDeliveryRepository
from vbwd.repositories.webhook_subscription_repository import (
    WebhookSubscriptionRepository,
)
from vbwd.utils.datetime_utils import utcnow
from vbwd.webhooks.event_types import TEST_EVENT
from vbwd.webhooks.signing import (
    DELIVERY_ID_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    compute_signature,
)

logger = logging.getLogger(__name__)

# Generated-secret length (URL-safe token characters).
SECRET_BYTES = 32

# Exponential backoff: ``BACKOFF_BASE_SECONDS * 2 ** attempt_count``, capped.
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 6 * 60 * 60  # 6 hours

# Per-request HTTP timeout for an outbound delivery POST.
DELIVERY_TIMEOUT_SECONDS = 5

# 2xx range is treated as a successful delivery.
SUCCESS_STATUS_MIN = 200
SUCCESS_STATUS_MAX = 299


class WebhookHttpResponse:
    """Minimal transport-agnostic response shape the deliverer consumes."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body


def _default_http_post(
    url: str, body: bytes, headers: dict, timeout: int
) -> WebhookHttpResponse:
    """Default HTTP transport — a thin wrapper over ``requests.post``."""
    import requests

    response = requests.post(url, data=body, headers=headers, timeout=timeout)
    return WebhookHttpResponse(response.status_code, response.text or "")


class OutboundWebhookService:
    """Enqueue + deliver outbound webhooks for the core event bus."""

    def __init__(
        self,
        subscription_repository: WebhookSubscriptionRepository,
        delivery_repository: WebhookDeliveryRepository,
        http_post: Optional[
            Callable[[str, bytes, dict, int], WebhookHttpResponse]
        ] = None,
    ):
        self._subscriptions = subscription_repository
        self._deliveries = delivery_repository
        self._http_post = http_post or _default_http_post

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        url: str,
        event_types: List[str],
        secret: Optional[str] = None,
        description: Optional[str] = None,
    ) -> WebhookSubscription:
        """Create a endpoint; generates a strong secret if none given."""
        normalized_url = (url or "").strip()
        if not normalized_url.startswith(("http://", "https://")):
            raise ValueError("url must be an http(s) URL")
        endpoint = WebhookSubscription(
            url=normalized_url,
            event_types=list(event_types or []),
            secret=secret or self._generate_secret(),
            description=description,
            is_active=True,
            consecutive_failure_count=0,
        )
        return self._subscriptions.save(endpoint)

    def list_all(self) -> List[WebhookSubscription]:
        """Return every endpoint, newest first."""
        return self._subscriptions.list_all()

    def get(self, webhook_id: Union[UUID, str]) -> Optional[WebhookSubscription]:
        """Return one endpoint or ``None``."""
        return self._subscriptions.find_by_id(webhook_id)

    def update(
        self,
        webhook_id: Union[UUID, str],
        url: Optional[str] = None,
        event_types: Optional[List[str]] = None,
        description: Optional[str] = None,
    ) -> WebhookSubscription:
        """Update a endpoint's writable fields."""
        endpoint = self._subscriptions.find_by_id(webhook_id)
        if endpoint is None:
            raise LookupError("webhook not found")
        if url is not None:
            normalized_url = url.strip()
            if not normalized_url.startswith(("http://", "https://")):
                raise ValueError("url must be an http(s) URL")
            endpoint.url = normalized_url
        if event_types is not None:
            endpoint.event_types = list(event_types)
        if description is not None:
            endpoint.description = description
        return self._subscriptions.save(endpoint)

    def delete(self, webhook_id: Union[UUID, str]) -> bool:
        """Delete a endpoint (cascades its deliveries)."""
        return self._subscriptions.delete(webhook_id)

    def toggle(self, webhook_id: Union[UUID, str]) -> WebhookSubscription:
        """Flip active state; re-enabling clears the failure counter."""
        endpoint = self._subscriptions.find_by_id(webhook_id)
        if endpoint is None:
            raise LookupError("webhook not found")
        endpoint.is_active = not endpoint.is_active
        if endpoint.is_active:
            endpoint.consecutive_failure_count = 0
        return self._subscriptions.save(endpoint)

    def list_deliveries(
        self, webhook_id: Union[UUID, str], limit: int = 50, offset: int = 0
    ) -> List[WebhookDelivery]:
        """Return deliveries for one endpoint, newest first."""
        return self._deliveries.find_by_webhook(webhook_id, limit=limit, offset=offset)

    # ------------------------------------------------------------------
    # Enqueue (synchronous, in the publishing request)
    # ------------------------------------------------------------------

    def enqueue_for_event(self, event_name: str, data: dict) -> int:
        """Insert a pending delivery per matching active endpoint.

        Fast: DB inserts only, never HTTP. Returns the number of deliveries
        enqueued. Updates each matched endpoint's ``last_triggered_at``.
        """
        endpoints = self._subscriptions.find_active_matching(event_name)
        if not endpoints:
            return 0
        now = utcnow()
        enqueued = 0
        for endpoint in endpoints:
            delivery = WebhookDelivery(
                webhook_id=endpoint.id,
                event_type=event_name,
                event_payload=data or {},
                status=STATUS_PENDING,
                attempt_count=0,
                next_attempt_at=now,
            )
            self._deliveries.save(delivery)
            endpoint.last_triggered_at = now
            self._subscriptions.save(endpoint)
            enqueued += 1
        return enqueued

    def send_test(self, webhook_id: Union[UUID, str]) -> WebhookDelivery:
        """Enqueue a synthetic ``webhook.test`` delivery and deliver it now."""
        endpoint = self._subscriptions.find_by_id(webhook_id)
        if endpoint is None:
            raise LookupError("webhook not found")
        now = utcnow()
        delivery = WebhookDelivery(
            webhook_id=endpoint.id,
            event_type=TEST_EVENT,
            event_payload={"message": "This is a test webhook delivery."},
            status=STATUS_PENDING,
            attempt_count=0,
            next_attempt_at=now,
        )
        delivery = self._deliveries.save(delivery)
        self._attempt_delivery(delivery, endpoint, now)
        return delivery

    # ------------------------------------------------------------------
    # Deliver (asynchronous, from the scheduler)
    # ------------------------------------------------------------------

    def deliver_due(self, now: Optional[datetime] = None, limit: int = 50) -> int:
        """Drain due deliveries, POST each, record the outcome.

        Never raises out of the drain: a failure to load/deliver one delivery
        is logged and the loop continues. Returns the number attempted.
        """
        now = now or utcnow()
        try:
            due = self._deliveries.find_due(now, limit=limit)
        except Exception as load_error:  # noqa: BLE001 — drain must not raise
            logger.warning("[webhook] Failed to load due deliveries: %s", load_error)
            return 0
        attempted = 0
        for delivery in due:
            endpoint = self._subscriptions.find_by_id(delivery.webhook_id)
            if endpoint is None:
                continue
            self._attempt_delivery(delivery, endpoint, now)
            attempted += 1
        return attempted

    def _attempt_delivery(
        self,
        delivery: WebhookDelivery,
        endpoint: WebhookSubscription,
        now: datetime,
    ) -> None:
        """Perform one POST and record success/failure + scheduling."""
        body = self._build_body(delivery)
        signature = compute_signature(endpoint.secret, body)
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: signature,
            EVENT_HEADER: delivery.event_type,
            DELIVERY_ID_HEADER: str(delivery.id),
            TIMESTAMP_HEADER: str(int(now.timestamp())),
        }
        delivery.attempt_count = (delivery.attempt_count or 0) + 1
        delivery.signature = signature
        try:
            response = self._http_post(
                endpoint.url, body, headers, DELIVERY_TIMEOUT_SECONDS
            )
        except Exception as transport_error:  # noqa: BLE001 — recorded, not raised
            self._record_failure(delivery, endpoint, str(transport_error), now)
            return

        delivery.response_code = response.status_code
        delivery.response_body = (response.body or "")[:MAX_RESPONSE_BODY_CHARS]
        if SUCCESS_STATUS_MIN <= response.status_code <= SUCCESS_STATUS_MAX:
            self._record_success(delivery, endpoint, now)
        else:
            self._record_failure(
                delivery,
                endpoint,
                f"non-2xx status {response.status_code}",
                now,
            )

    def _record_success(
        self,
        delivery: WebhookDelivery,
        endpoint: WebhookSubscription,
        now: datetime,
    ) -> None:
        delivery.status = STATUS_SUCCESS
        delivery.delivered_at = now
        delivery.error = None
        delivery.next_attempt_at = None
        self._deliveries.save(delivery)
        endpoint.consecutive_failure_count = 0
        self._subscriptions.save(endpoint)

    def _record_failure(
        self,
        delivery: WebhookDelivery,
        endpoint: WebhookSubscription,
        error: str,
        now: datetime,
    ) -> None:
        delivery.error = error
        if delivery.attempt_count < delivery.max_attempts:
            delivery.status = STATUS_PENDING
            delivery.next_attempt_at = now + self._backoff(delivery.attempt_count)
            self._deliveries.save(delivery)
            return

        # Exhausted: mark failed and count it against the endpoint.
        delivery.status = STATUS_FAILED
        delivery.next_attempt_at = None
        self._deliveries.save(delivery)
        endpoint.consecutive_failure_count = (
            endpoint.consecutive_failure_count or 0
        ) + 1
        if endpoint.consecutive_failure_count >= AUTO_DISABLE_FAILURE_THRESHOLD:
            endpoint.is_active = False
            logger.warning(
                "[webhook] Auto-disabled endpoint %s after %d consecutive " "failures",
                endpoint.id,
                endpoint.consecutive_failure_count,
            )
        self._subscriptions.save(endpoint)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_body(delivery: WebhookDelivery) -> bytes:
        """Build the exact JSON body bytes that are signed and sent."""
        envelope = {
            "id": str(delivery.id),
            "event_type": delivery.event_type,
            "created_at": (
                delivery.created_at.isoformat() if delivery.created_at else None
            ),
            "data": delivery.event_payload or {},
        }
        return json.dumps(envelope, sort_keys=True, default=str).encode("utf-8")

    @staticmethod
    def _backoff(attempt_count: int) -> timedelta:
        """Exponential backoff delay for the given attempt number, capped."""
        seconds = BACKOFF_BASE_SECONDS * (2**attempt_count)
        return timedelta(seconds=min(seconds, BACKOFF_CAP_SECONDS))

    @staticmethod
    def _generate_secret() -> str:
        """Generate a strong URL-safe signing secret."""
        return secrets.token_urlsafe(SECRET_BYTES)
