"""Password reset token repository."""
from datetime import datetime
from src.utils.datetime_utils import utcnow
from typing import Optional
from uuid import UUID
from sqlalchemy.orm import Session
from src.models.password_reset_token import PasswordResetToken
from src.repositories.base import BaseRepository


class PasswordResetRepository(BaseRepository[PasswordResetToken]):
    """Repository for password reset token operations."""

    def __init__(self, session: Session):
        """Initialize repository with database session."""
        super().__init__(session, PasswordResetToken)

    def find_by_token(self, token: str) -> Optional[PasswordResetToken]:
        """
        Find password reset token by token string.

        Args:
            token: The token string to find

        Returns:
            PasswordResetToken if found, None otherwise
        """
        return (
            self._session.query(PasswordResetToken)
            .filter(PasswordResetToken.token == token)
            .first()
        )

    def create_token(
        self, user_id: UUID, token: str, expires_at: datetime
    ) -> PasswordResetToken:
        """
        Create a new password reset token.

        Args:
            user_id: UUID of the user requesting reset
            token: Secure random token string
            expires_at: Token expiration datetime

        Returns:
            Created PasswordResetToken
        """
        reset_token = PasswordResetToken()
        reset_token.user_id = user_id
        reset_token.token = token
        reset_token.expires_at = expires_at

        self._session.add(reset_token)
        self._session.commit()

        return reset_token

    def invalidate_tokens_for_user(self, user_id: UUID) -> int:
        """
        Invalidate all existing tokens for a user.

        Args:
            user_id: UUID of the user

        Returns:
            Number of tokens invalidated
        """
        count = (
            self._session.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .update({"used_at": utcnow()}, synchronize_session=False)
        )
        self._session.commit()
        return count

    def mark_used(self, token_id: UUID) -> bool:
        """
        Mark a token as used.

        Args:
            token_id: UUID of the token

        Returns:
            True if token was marked, False if not found
        """
        token = self.find_by_id(token_id)
        if token:
            token.used_at = utcnow()
            self._session.commit()
            return True
        return False

    def cleanup_expired(self, older_than_days: int = 7) -> int:
        """
        Delete expired tokens older than specified days.

        Args:
            older_than_days: Delete tokens expired more than this many days ago

        Returns:
            Number of tokens deleted
        """
        from datetime import timedelta

        cutoff = utcnow() - timedelta(days=older_than_days)

        count = (
            self._session.query(PasswordResetToken)
            .filter(PasswordResetToken.expires_at < cutoff)
            .delete(synchronize_session=False)
        )

        self._session.commit()
        return count
