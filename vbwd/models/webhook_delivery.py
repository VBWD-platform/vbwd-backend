"""Outbound webhook delivery attempt model (core, plugin-agnostic).

A :class:`WebhookDelivery` is one queued/attempted delivery of a single event
to a single :class:`~vbwd.models.webhook_subscription.WebhookSubscription`. It
is created synchronously when an event is published (status ``pending``) and
drained asynchronously by the scheduler, which performs the HTTP POST and
records the outcome.

The fe-admin ``stores/webhooks.ts`` ``WebhookDelivery`` interface is the
binding contract for :meth:`to_dict`:

    { id, event_type, status: 'success'|'failed'|'pending',
      response_code, response_body, created_at }
"""
from sqlalchemy.dialects.postgresql import JSONB, UUID

from vbwd.extensions import db
from vbwd.models.base import BaseModel

# Truncate stored response bodies so a chatty subscriber can't bloat the table.
MAX_RESPONSE_BODY_CHARS = 2048

# Default maximum delivery attempts before a delivery is marked 'failed'.
DEFAULT_MAX_ATTEMPTS = 5

STATUS_PENDING = "pending"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


class WebhookDelivery(BaseModel):
    """A single delivery attempt of an event to a subscription."""

    __tablename__ = "vbwd_webhook_delivery"

    webhook_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_webhook.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = db.Column(db.String(length=255), nullable=False)
    event_payload = db.Column(JSONB, nullable=False, default=dict)
    status = db.Column(db.String(length=20), nullable=False, default=STATUS_PENDING)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=DEFAULT_MAX_ATTEMPTS)
    next_attempt_at = db.Column(db.DateTime, nullable=True, index=True)
    response_code = db.Column(db.Integer, nullable=True)
    response_body = db.Column(db.Text, nullable=True)
    error = db.Column(db.Text, nullable=True)
    signature = db.Column(db.String(length=128), nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self) -> dict:
        """Serialize to the fe ``WebhookDelivery`` shape."""
        return {
            "id": str(self.id),
            "webhook_id": str(self.webhook_id),
            "event_type": self.event_type,
            "status": self.status,
            "response_code": self.response_code,
            "response_body": self.response_body,
            "error": self.error,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "delivered_at": (
                self.delivered_at.isoformat() if self.delivered_at else None
            ),
        }
