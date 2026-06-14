"""Core device-token service (S66).

Register / unregister / mark-seen for push device tokens. Register is
idempotent: an upsert by token — if another user previously registered the
same token (device handoff after wipe-and-reinstall), the latest user wins
and ``last_seen_at`` is refreshed; a row is never duplicated.
"""
from typing import List, Optional, Union
from uuid import UUID

from vbwd.models.device_token import DeviceToken
from vbwd.repositories.device_token_repository import DeviceTokenRepository
from vbwd.utils.datetime_utils import utcnow

SUPPORTED_PLATFORMS = ("ios",)


class UnsupportedPlatformError(ValueError):
    """The requested platform is not supported (v1: ios only)."""


class DeviceTokenService:
    """Business rules around the generic device-token mechanism."""

    def __init__(self, repository: DeviceTokenRepository) -> None:
        self._repository = repository

    def register(
        self,
        *,
        user_id: Union[UUID, str],
        token: str,
        platform: str,
        bundle_id: str,
        app: str,
    ) -> DeviceToken:
        """Upsert a device token for ``user_id`` (idempotent by token)."""
        cleaned_token = (token or "").strip()
        if not cleaned_token:
            raise ValueError("token is required")
        if platform not in SUPPORTED_PLATFORMS:
            raise UnsupportedPlatformError(
                f"platform must be one of: {', '.join(SUPPORTED_PLATFORMS)}"
            )

        row = self._repository.find_by_token(cleaned_token)
        if row is None:
            row = DeviceToken()
            row.token = cleaned_token
        row.user_id = user_id
        row.platform = platform
        row.bundle_id = bundle_id
        row.app = app
        row.last_seen_at = utcnow()
        row.revoked_at = None
        return self._repository.save(row)

    def unregister(self, token: str) -> Optional[DeviceToken]:
        """Mark a token revoked. Idempotent; returns None for unknown tokens."""
        row = self._repository.find_by_token((token or "").strip())
        if row is None:
            return None
        if row.revoked_at is None:
            row.revoked_at = utcnow()
            return self._repository.save(row)
        return row

    def mark_seen(self, token: str) -> None:
        """Refresh ``last_seen_at`` for an existing token (no-op if unknown)."""
        row = self._repository.find_by_token((token or "").strip())
        if row is None:
            return
        row.last_seen_at = utcnow()
        self._repository.save(row)

    def find_by_token(self, token: str) -> Optional[DeviceToken]:
        """Owner lookups (the DELETE route's ownership check)."""
        return self._repository.find_by_token((token or "").strip())

    def find_active(self, user_id: Union[UUID, str], app: str) -> List[DeviceToken]:
        """A user's non-revoked tokens for one client app."""
        return self._repository.find_active_by_user_and_app(user_id, app)
