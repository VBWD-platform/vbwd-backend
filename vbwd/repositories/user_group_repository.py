"""Repository for the core ``UserGroup`` model (S73)."""
from typing import List, Optional

from vbwd.models.user_group import UserGroup
from vbwd.repositories.base import BaseRepository


class UserGroupRepository(BaseRepository[UserGroup]):
    """Data access for user groups."""

    def __init__(self, session):
        super().__init__(session, UserGroup)

    def find_by_slug(self, slug: str) -> Optional[UserGroup]:
        """Find a group by its unique slug."""
        return self._session.query(UserGroup).filter_by(slug=slug).first()

    def list_all(self) -> List[UserGroup]:
        """Return every group ordered by slug (stable list page order)."""
        return self._session.query(UserGroup).order_by(UserGroup.slug).all()
