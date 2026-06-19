"""Outbound webhook subscription model (core, plugin-agnostic).

A :class:`WebhookSubscription` is an admin-registered endpoint that wants to
receive a relayed copy of domain events published on the core event bus. It is
pure core infrastructure: it relays *whatever* event names are published and
never imports or names any plugin domain.

The fe-admin ``stores/webhooks.ts`` ``Webhook`` interface is the binding
contract for :meth:`to_dict`:

    { id, url, events[], status: 'active'|'inactive'|'failed',
      secret, created_at, last_triggered_at }

The persisted columns are ``is_active`` (bool) + ``consecutive_failure_count``
(int); :meth:`to_dict` maps them onto the surfaced ``status`` string:
``inactive`` when ``is_active`` is false, ``failed`` when the subscription was
auto-disabled after repeated delivery failures, ``active`` otherwise.
"""
from sqlalchemy.dialects.postgresql import JSONB

from vbwd.extensions import db
from vbwd.models.base import BaseModel

# How many *consecutive* failed deliveries auto-disable a subscription. Once
# tripped, the subscription is set inactive and surfaced with status 'failed'
# so the admin sees it needs attention.
AUTO_DISABLE_FAILURE_THRESHOLD = 5

# Sentinel event name in ``event_types`` meaning "every event".
WILDCARD_EVENT = "*"

# Surfaced status strings (the fe ``Webhook.status`` union).
STATUS_ACTIVE = "active"
STATUS_INACTIVE = "inactive"
STATUS_FAILED = "failed"


class WebhookSubscription(BaseModel):
    """An admin-registered outbound webhook endpoint."""

    __tablename__ = "vbwd_webhook"

    url = db.Column(db.String(length=2048), nullable=False)
    secret = db.Column(db.String(length=128), nullable=False)
    # JSON array of event-name strings; ``["*"]`` means "all events".
    event_types = db.Column(JSONB, nullable=False, default=list)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    description = db.Column(db.Text, nullable=True)
    last_triggered_at = db.Column(db.DateTime, nullable=True)
    consecutive_failure_count = db.Column(db.Integer, nullable=False, default=0)

    @property
    def status(self) -> str:
        """Map the persisted flags onto the surfaced fe status string."""
        if self.is_active:
            return STATUS_ACTIVE
        if (self.consecutive_failure_count or 0) >= AUTO_DISABLE_FAILURE_THRESHOLD:
            return STATUS_FAILED
        return STATUS_INACTIVE

    def matches_event(self, event_name: str) -> bool:
        """Return True if this subscription wants ``event_name``."""
        event_types = self.event_types or []
        return WILDCARD_EVENT in event_types or event_name in event_types

    def to_dict(self) -> dict:
        """Serialize to the fe ``Webhook`` shape."""
        return {
            "id": str(self.id),
            "url": self.url,
            "events": list(self.event_types or []),
            "status": self.status,
            "secret": self.secret,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_triggered_at": (
                self.last_triggered_at.isoformat() if self.last_triggered_at else None
            ),
        }
