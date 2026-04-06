"""Service for managing user access level assignments."""
import logging
from typing import Optional, List
from uuid import UUID

from vbwd.extensions import db
from vbwd.models.user import User
from vbwd.models.user_access_level import UserAccessLevel

logger = logging.getLogger(__name__)


class UserAccessLevelService:
    """Core service for assigning and revoking user access levels.

    Plugins call this service to manage user-facing permissions.
    The service is agnostic — it does not know about plans or subscriptions.
    """

    def __init__(self, session=None):
        self._session = session or db.session

    def find_by_slug(self, slug: str) -> Optional[UserAccessLevel]:
        """Find an access level by slug."""
        return (
            self._session.query(UserAccessLevel)
            .filter(UserAccessLevel.slug == slug)
            .first()
        )

    def find_by_linked_plan_slug(self, plan_slug: str) -> Optional[UserAccessLevel]:
        """Find an access level linked to a specific plan slug."""
        return (
            self._session.query(UserAccessLevel)
            .filter(UserAccessLevel.linked_plan_slug == plan_slug)
            .first()
        )

    def find_all_by_linked_plan_slug(self, plan_slug: str) -> List[UserAccessLevel]:
        """Find all access levels linked to a specific plan slug."""
        return (
            self._session.query(UserAccessLevel)
            .filter(UserAccessLevel.linked_plan_slug == plan_slug)
            .all()
        )

    def assign(self, user_id: UUID, level_id: UUID) -> bool:
        """Assign a user access level to a user.

        No-op if the user already has the level.

        Returns:
            True if level was assigned, False if already assigned or not found.
        """
        user = self._session.get(User, user_id)
        if not user:
            logger.warning("Cannot assign access level: user %s not found", user_id)
            return False

        level = self._session.get(UserAccessLevel, level_id)
        if not level:
            logger.warning("Cannot assign access level: level %s not found", level_id)
            return False

        existing_level_ids = {
            lvl.id for lvl in user.assigned_user_access_levels
        }
        if level.id in existing_level_ids:
            logger.debug(
                "User %s already has access level %s", user_id, level.slug
            )
            return False

        user.assigned_user_access_levels.append(level)
        self._session.flush()
        logger.info(
            "Assigned access level '%s' to user %s", level.slug, user_id
        )
        return True

    def revoke(self, user_id: UUID, level_id: UUID) -> bool:
        """Revoke a user access level from a user.

        No-op if the user doesn't have the level.

        Returns:
            True if level was revoked, False if not found or not assigned.
        """
        user = self._session.get(User, user_id)
        if not user:
            logger.warning("Cannot revoke access level: user %s not found", user_id)
            return False

        level = self._session.get(UserAccessLevel, level_id)
        if not level:
            logger.warning("Cannot revoke access level: level %s not found", level_id)
            return False

        existing_levels = list(user.assigned_user_access_levels)
        if level not in existing_levels:
            logger.debug(
                "User %s does not have access level %s", user_id, level.slug
            )
            return False

        user.assigned_user_access_levels.remove(level)
        self._session.flush()
        logger.info(
            "Revoked access level '%s' from user %s", level.slug, user_id
        )
        return True

    def revoke_plan_linked_levels(self, user_id: UUID, plan_slug: str) -> int:
        """Revoke all access levels linked to a specific plan slug.

        Returns:
            Number of levels revoked.
        """
        levels = self.find_all_by_linked_plan_slug(plan_slug)
        revoked_count = 0
        for level in levels:
            if self.revoke(user_id, level.id):
                revoked_count += 1
        return revoked_count

    def get_user_levels(self, user_id: UUID) -> List[UserAccessLevel]:
        """Get all access levels assigned to a user."""
        user = self._session.get(User, user_id)
        if not user:
            return []
        return list(user.assigned_user_access_levels)
