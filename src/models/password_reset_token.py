"""Password reset token model."""
from sqlalchemy.dialects.postgresql import UUID
from src.extensions import db
from src.models.base import BaseModel
from src.utils.datetime_utils import utcnow


class PasswordResetToken(BaseModel):
    """
    Password reset token model.

    Stores tokens for password reset requests with expiration and usage tracking.
    """

    __tablename__ = "password_reset_token"

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)

    # Relationship
    user = db.relationship("User", backref=db.backref("reset_tokens", lazy="dynamic"))

    def __repr__(self) -> str:
        return f"<PasswordResetToken(id={self.id}, user_id={self.user_id})>"

    @property
    def is_expired(self) -> bool:
        """Check if token has expired."""
        return self.expires_at < utcnow()

    @property
    def is_used(self) -> bool:
        """Check if token has been used."""
        return self.used_at is not None

    @property
    def is_valid(self) -> bool:
        """Check if token is valid (not expired and not used)."""
        return not self.is_expired and not self.is_used
