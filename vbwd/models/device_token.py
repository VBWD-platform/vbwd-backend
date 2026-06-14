"""Core device-token model (S66).

A generic, domain-neutral push-notification mechanism entity: a user's
device registers an opaque platform token for a named client app. Core
never interprets what the app does with pushes — plugins translate their
domain events into payloads via the push dispatcher registry.
"""
from sqlalchemy.dialects.postgresql import UUID

from vbwd.extensions import db
from vbwd.models.base import BaseModel
from vbwd.utils.datetime_utils import utcnow


class DeviceToken(BaseModel):
    """A device's push token, owned by a user, scoped to a client app.

    ``token`` is unique across all users — re-registering an existing token
    upserts (the latest user wins; device handoff after wipe-and-reinstall).
    ``revoked_at`` is set on unregister or when APNs reports the token stale
    (410); revoked rows are excluded from dispatch.
    """

    __tablename__ = "vbwd_device_token"
    __table_args__ = (
        db.Index(
            "ix_vbwd_device_token_user_app_revoked",
            "user_id",
            "app",
            "revoked_at",
        ),
    )

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    token = db.Column(db.Text, unique=True, nullable=False)
    platform = db.Column(db.String(16), nullable=False)
    bundle_id = db.Column(db.String(255), nullable=False)
    app = db.Column(db.String(64), nullable=False)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    revoked_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<DeviceToken(id={self.id}, user_id={self.user_id}, "
            f"platform={self.platform}, app={self.app})>"
        )

    def to_dict(self) -> dict:
        """Serialise for API responses (the owner sees their own tokens)."""
        return {
            "id": str(self.id) if self.id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "token": self.token,
            "platform": self.platform,
            "bundle_id": self.bundle_id,
            "app": self.app,
            "last_seen_at": (
                self.last_seen_at.isoformat() if self.last_seen_at else None
            ),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
