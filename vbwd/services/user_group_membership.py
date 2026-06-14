"""Core write port for slug-keyed user-group membership (S73).

Core owns the ``UserGroup`` entity and the ``vbwd_user_group_rel`` M2M; plugins
must not import the model. This module exposes one narrow write port,
``IUserGroupMembership``, that the subscription plugin resolves to add/remove a
user's group memberships (by slug) when a plan/add-on declares a check-in /
check-out group. The default implementation writes directly to the rel table.

Registry mirrors ``vbwd.services.user_permission_grant`` /
``vbwd.services.entitlement``: a module global plus ``register_*`` / ``clear_*``
/ ``resolve_*`` helpers. ``resolve_*`` returns a default instance when none is
registered, so callers never branch on wiring (Liskov: the default honours the
same contract).
"""
import logging
from abc import ABC, abstractmethod
from typing import Iterable, Set
from uuid import UUID

from sqlalchemy import delete, insert, select

logger = logging.getLogger(__name__)


class IUserGroupMembership(ABC):
    """Narrow write port (ISP) — only what the membership consumer needs.

    All methods are idempotent: ``add`` of a slug the user already has is a
    no-op, ``remove`` of one they lack is a no-op, ``set_user_groups`` replaces
    the whole membership set, and ``list_user_group_slugs`` reads it back.
    """

    @abstractmethod
    def list_user_group_slugs(self, user_id: UUID) -> Set[str]:
        """Return the set of group slugs the user currently belongs to."""

    @abstractmethod
    def set_user_groups(self, user_id: UUID, slugs: Iterable[str]) -> None:
        """Replace the user's membership set with exactly ``slugs``."""

    @abstractmethod
    def add(self, user_id: UUID, slug: str) -> None:
        """Add the user to the group (no-op if already a member)."""

    @abstractmethod
    def remove(self, user_id: UUID, slug: str) -> None:
        """Remove the user from the group (no-op if not a member)."""


class DefaultUserGroupMembership(IUserGroupMembership):
    """Default impl writing directly to ``vbwd_user_group_rel``.

    Only writes rows whose ``group_slug`` references an existing group (the FK
    would otherwise fail); ``set_user_groups`` / ``add`` skip unknown slugs with
    a logged warning so a stale config never aborts a reconcile.
    """

    def __init__(self, session=None):
        from vbwd.extensions import db

        self._session = session or db.session

    def _rel_table(self):
        from vbwd.models.user_group import user_group_rel

        return user_group_rel

    def _known_group_slugs(self) -> Set[str]:
        from vbwd.models.user_group import UserGroup

        rows = self._session.query(UserGroup.slug).all()
        return {row[0] for row in rows}

    def list_user_group_slugs(self, user_id: UUID) -> Set[str]:
        rel = self._rel_table()
        rows = self._session.execute(
            select(rel.c.group_slug).where(rel.c.user_id == user_id)
        ).all()
        return {row[0] for row in rows}

    def set_user_groups(self, user_id: UUID, slugs: Iterable[str]) -> None:
        desired = {slug for slug in slugs if slug}
        current = self.list_user_group_slugs(user_id)
        for slug in desired - current:
            self.add(user_id, slug)
        for slug in current - desired:
            self.remove(user_id, slug)

    def add(self, user_id: UUID, slug: str) -> None:
        if slug in self.list_user_group_slugs(user_id):
            return
        if slug not in self._known_group_slugs():
            logger.warning(
                "[user-group] unknown group slug '%s' — membership add skipped", slug
            )
            return
        rel = self._rel_table()
        self._session.execute(insert(rel).values(user_id=user_id, group_slug=slug))

    def remove(self, user_id: UUID, slug: str) -> None:
        rel = self._rel_table()
        self._session.execute(
            delete(rel).where(rel.c.user_id == user_id, rel.c.group_slug == slug)
        )


_membership = None


def register_user_group_membership(membership: IUserGroupMembership) -> None:
    """Register a custom membership impl (composition root / tests)."""
    global _membership
    _membership = membership


def clear_user_group_membership() -> None:
    """Reset to the default (test teardown)."""
    global _membership
    _membership = None


def resolve_user_group_membership() -> IUserGroupMembership:
    """The registered membership impl, or a fresh default when none is set."""
    return _membership if _membership is not None else DefaultUserGroupMembership()
