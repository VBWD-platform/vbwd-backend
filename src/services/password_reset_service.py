"""Password reset service implementation."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from src.utils.datetime_utils import utcnow
from typing import Optional
import secrets

from src.repositories.user_repository import UserRepository
from src.repositories.password_reset_repository import PasswordResetRepository
from src.services.auth_service import AuthService


@dataclass
class ResetRequestResult:
    """Result of password reset request."""

    success: bool
    user_id: Optional[str] = None
    email: Optional[str] = None
    token: Optional[str] = None
    expires_at: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class ResetResult:
    """Result of password reset execution."""

    success: bool
    user_id: Optional[str] = None
    email: Optional[str] = None
    error: Optional[str] = None
    failure_reason: Optional[str] = None  # "invalid", "expired", "already_used"


class PasswordResetService:
    """
    Password reset business logic.

    Pure service - does NOT emit events. That's the route's job.
    """

    TOKEN_EXPIRY_HOURS = 1

    def __init__(
        self,
        user_repository: UserRepository,
        reset_repository: PasswordResetRepository,
    ):
        """
        Initialize service with repositories.

        Args:
            user_repository: Repository for user data access
            reset_repository: Repository for password reset tokens
        """
        self._user_repo = user_repository
        self._reset_repo = reset_repository

    def create_reset_token(self, email: str) -> ResetRequestResult:
        """
        Create password reset token for user.

        Returns success even if user not found (security - don't reveal existence).

        Args:
            email: User email address

        Returns:
            ResetRequestResult with token data if user exists
        """
        user = self._user_repo.find_by_email(email)

        if not user:
            # Don't reveal if email exists - return success but no data
            return ResetRequestResult(success=True)

        # Invalidate any existing tokens
        self._reset_repo.invalidate_tokens_for_user(user.id)  # type: ignore[arg-type]

        # Generate secure token
        token = secrets.token_urlsafe(32)
        expires_at = utcnow() + timedelta(hours=self.TOKEN_EXPIRY_HOURS)

        # Store token
        self._reset_repo.create_token(
            user_id=user.id, token=token, expires_at=expires_at  # type: ignore[arg-type]
        )

        return ResetRequestResult(
            success=True,
            user_id=str(user.id),
            email=user.email,
            token=token,
            expires_at=expires_at,
        )

    def reset_password(self, token: str, new_password: str) -> ResetResult:
        """
        Reset password using token.

        Args:
            token: Password reset token
            new_password: New password to set

        Returns:
            ResetResult with success/failure and user info
        """
        reset_token = self._reset_repo.find_by_token(token)

        if not reset_token:
            return ResetResult(
                success=False, error="Invalid token", failure_reason="invalid"
            )

        if reset_token.expires_at < utcnow():
            return ResetResult(
                success=False, error="Token expired", failure_reason="expired"
            )

        if reset_token.used_at is not None:
            return ResetResult(
                success=False, error="Token already used", failure_reason="already_used"
            )

        # Get user and update password
        user = self._user_repo.find_by_id(reset_token.user_id)
        if not user:
            return ResetResult(
                success=False, error="User not found", failure_reason="invalid"
            )

        # Hash new password using AuthService
        auth_service = AuthService(self._user_repo)
        user.password_hash = auth_service.hash_password(new_password)

        # Update user
        self._user_repo.update(user)

        # Mark token as used
        self._reset_repo.mark_used(reset_token.id)  # type: ignore[arg-type]

        return ResetResult(success=True, user_id=str(user.id), email=user.email)
