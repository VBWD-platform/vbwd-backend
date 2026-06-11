"""Core API-key repository (S52)."""
from typing import List, Optional, Union
from uuid import UUID

from vbwd.models.api_key import ApiKey
from vbwd.repositories.base import BaseRepository


class ApiKeyRepository(BaseRepository[ApiKey]):
    """Data access for ``ApiKey`` rows."""

    def __init__(self, session):
        super().__init__(session, ApiKey)

    def find_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        """Look up a key by its sha256 hash (the guard's primary lookup)."""
        return self._session.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()

    def find_by_user(self, user_id: Union[UUID, str]) -> List[ApiKey]:
        """List a user's keys, newest first."""
        return (
            self._session.query(ApiKey)
            .filter(ApiKey.user_id == user_id)
            .order_by(ApiKey.created_at.desc())
            .all()
        )

    def revoke(self, key_id: Union[UUID, str]) -> bool:
        """Deactivate a key (audit row kept). Returns False when absent."""
        api_key = self.find_by_id(key_id)
        if not api_key:
            return False
        api_key.is_active = False
        self._session.commit()
        return True
