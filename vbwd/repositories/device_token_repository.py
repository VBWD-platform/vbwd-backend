"""Core device-token repository (S66)."""
from typing import List, Optional, Union
from uuid import UUID

from vbwd.models.device_token import DeviceToken
from vbwd.repositories.base import BaseRepository


class DeviceTokenRepository(BaseRepository[DeviceToken]):
    """Data access for ``DeviceToken`` rows."""

    def __init__(self, session):
        super().__init__(session, DeviceToken)

    def find_by_token(self, token: str) -> Optional[DeviceToken]:
        """Look up a row by its (unique) device token."""
        return (
            self._session.query(DeviceToken).filter(DeviceToken.token == token).first()
        )

    def find_active_by_user_and_app(
        self, user_id: Union[UUID, str], app: str
    ) -> List[DeviceToken]:
        """A user's non-revoked tokens for one client app, newest-seen first."""
        return (
            self._session.query(DeviceToken)
            .filter(DeviceToken.user_id == user_id)
            .filter(DeviceToken.app == app)
            .filter(DeviceToken.revoked_at.is_(None))
            .order_by(DeviceToken.last_seen_at.desc())
            .all()
        )
