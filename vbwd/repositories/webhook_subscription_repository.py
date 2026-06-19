"""Repository for :class:`WebhookSubscription` (outbound webhooks, core)."""
from typing import List

from vbwd.models.webhook_subscription import WebhookSubscription
from vbwd.repositories.base import BaseRepository


class WebhookSubscriptionRepository(BaseRepository[WebhookSubscription]):
    """Data access for outbound webhook endpoints."""

    def __init__(self, session):
        super().__init__(session, WebhookSubscription)

    def list_all(self) -> List[WebhookSubscription]:
        """Return every endpoint, newest first."""
        return (
            self._session.query(WebhookSubscription)
            .order_by(WebhookSubscription.created_at.desc())
            .all()
        )

    def find_active_matching(self, event_name: str) -> List[WebhookSubscription]:
        """Return active endpoints whose ``event_types`` match ``event_name``.

        A endpoint matches when its ``event_types`` array contains the exact
        event name or the ``"*"`` wildcard. The match is applied in Python so
        the behaviour is identical across JSON backends.
        """
        active = (
            self._session.query(WebhookSubscription)
            .filter(WebhookSubscription.is_active.is_(True))
            .all()
        )
        return [endpoint for endpoint in active if endpoint.matches_event(event_name)]
