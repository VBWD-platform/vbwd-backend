"""Core API-key model (S52).

A generic, domain-neutral auth-mechanism entity: a user holds scoped,
IP-restricted API keys. The plaintext token is **never** persisted — only its
sha256 hash (``key_hash``) and a short display prefix (``key_prefix``). The
``scopes`` allow-list holds opaque scope strings that plugins define; core
never interprets them.
"""
from sqlalchemy.dialects.postgresql import JSONB, UUID

from vbwd.extensions import db
from vbwd.models.base import BaseModel


class ApiKey(BaseModel):
    """Scoped, IP-restricted API key owned by a user.

    Protected endpoints authenticate via the core ``require_api_key`` guard and
    then act as ``user_id`` (the owner). Revoking flips ``is_active`` (the audit
    row is kept).
    """

    __tablename__ = "vbwd_api_key"

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label = db.Column(db.String(120), nullable=False)
    key_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    key_prefix = db.Column(db.String(16), nullable=False)
    scopes = db.Column(JSONB, nullable=False, default=list)
    ip_whitelist = db.Column(JSONB, nullable=False, default=list)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by_user_id = db.Column(UUID(as_uuid=True), nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ApiKey(id={self.id}, prefix={self.key_prefix}, user_id={self.user_id})>"
        )

    def to_dict(self) -> dict:
        """Serialise for API responses.

        Deliberately excludes ``key_hash`` — the secret hash must never leave
        the service boundary. Only the display ``key_prefix`` is exposed.
        """
        return {
            "id": str(self.id) if self.id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "label": self.label,
            "key_prefix": self.key_prefix,
            "scopes": list(self.scopes or []),
            "ip_whitelist": list(self.ip_whitelist or []),
            "is_active": self.is_active,
            "created_by_user_id": (
                str(self.created_by_user_id) if self.created_by_user_id else None
            ),
            "last_used_at": (
                self.last_used_at.isoformat() if self.last_used_at else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
