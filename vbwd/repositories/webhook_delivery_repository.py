"""Repository for :class:`WebhookDelivery` (outbound webhooks, core)."""
from datetime import datetime
from typing import List, Union
from uuid import UUID

from vbwd.models.webhook_delivery import WebhookDelivery
from vbwd.repositories.base import BaseRepository


class WebhookDeliveryRepository(BaseRepository[WebhookDelivery]):
    """Data access for outbound webhook delivery attempts."""

    def __init__(self, session):
        super().__init__(session, WebhookDelivery)

    def find_due(self, now: datetime, limit: int = 50) -> List[WebhookDelivery]:
        """Return pending deliveries that are due for an attempt.

        Due means: status is ``pending``, attempts remain
        (``attempt_count < max_attempts``), and ``next_attempt_at`` is at or
        before ``now``. Oldest-due first so retries do not starve.
        """
        from vbwd.models.webhook_delivery import STATUS_PENDING

        return (
            self._session.query(WebhookDelivery)
            .filter(WebhookDelivery.status == STATUS_PENDING)
            .filter(WebhookDelivery.attempt_count < WebhookDelivery.max_attempts)
            .filter(WebhookDelivery.next_attempt_at <= now)
            .order_by(WebhookDelivery.next_attempt_at.asc())
            .limit(limit)
            .all()
        )

    def find_by_webhook(
        self, webhook_id: Union[UUID, str], limit: int = 50, offset: int = 0
    ) -> List[WebhookDelivery]:
        """Return deliveries for one subscription, newest first, paginated."""
        return (
            self._session.query(WebhookDelivery)
            .filter(WebhookDelivery.webhook_id == webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
