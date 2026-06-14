"""Core ``UserGroup`` CRUD service (S73).

Owns slug validation, parent_group integrity (must reference an existing slug or
be null), and bulk delete. Pure orchestration over ``UserGroupRepository`` and
the session — no plugin knowledge (core stays agnostic).
"""
import re
from typing import List, Optional
from uuid import uuid4

from vbwd.models.user_group import UserGroup
from vbwd.repositories.user_group_repository import UserGroupRepository

# A slug is a lowercase identifier of letters, digits and hyphens — portable as
# a natural key and as an FK target across instances.
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class UserGroupValidationError(Exception):
    """Raised when a group create/update payload is invalid."""


class UserGroupService:
    """CRUD + list + bulk-delete for user groups."""

    def __init__(self, session, repository: Optional[UserGroupRepository] = None):
        self._session = session
        self._repository = repository or UserGroupRepository(session)

    def list_groups(self) -> List[UserGroup]:
        return self._repository.list_all()

    def get_by_id(self, group_id) -> Optional[UserGroup]:
        return self._repository.find_by_id(group_id)

    def get_by_slug(self, slug: str) -> Optional[UserGroup]:
        return self._repository.find_by_slug(slug)

    def create_group(
        self,
        *,
        slug: str,
        name: str,
        lang: Optional[str] = None,
        parent_group: Optional[str] = None,
    ) -> UserGroup:
        slug = self._validate_slug(slug)
        name = self._validate_name(name)
        if self._repository.find_by_slug(slug) is not None:
            raise UserGroupValidationError(f"Group slug '{slug}' already exists")
        self._validate_parent_group(parent_group, current_slug=slug)

        group = UserGroup(
            id=uuid4(),
            slug=slug,
            name=name,
            lang=lang or None,
            parent_group=parent_group or None,
        )
        self._session.add(group)
        self._session.commit()
        return group

    def update_group(self, group_id, payload: dict) -> Optional[UserGroup]:
        group = self._repository.find_by_id(group_id)
        if group is None:
            return None

        if "slug" in payload:
            new_slug = self._validate_slug(payload["slug"])
            existing = self._repository.find_by_slug(new_slug)
            if existing is not None and str(existing.id) != str(group.id):
                raise UserGroupValidationError(
                    f"Group slug '{new_slug}' already exists"
                )
            group.slug = new_slug
        if "name" in payload:
            group.name = self._validate_name(payload["name"])
        if "lang" in payload:
            group.lang = payload["lang"] or None
        if "parent_group" in payload:
            parent_group = payload["parent_group"] or None
            self._validate_parent_group(parent_group, current_slug=group.slug)
            group.parent_group = parent_group

        self._session.commit()
        return group

    def delete_group(self, group_id) -> bool:
        group = self._repository.find_by_id(group_id)
        if group is None:
            return False
        self._session.delete(group)
        self._session.commit()
        return True

    def bulk_delete(self, group_ids: List[str]) -> int:
        """Delete the groups with the given ids; returns how many were removed."""
        deleted = 0
        for group_id in group_ids:
            group = self._repository.find_by_id(group_id)
            if group is not None:
                self._session.delete(group)
                deleted += 1
        self._session.commit()
        return deleted

    # ── validation ───────────────────────────────────────────────────────────

    def _validate_slug(self, slug) -> str:
        slug = (slug or "").strip()
        if not slug:
            raise UserGroupValidationError("slug is required")
        if not SLUG_PATTERN.match(slug):
            raise UserGroupValidationError(
                "slug must be lowercase letters, digits and hyphens"
            )
        return slug

    def _validate_name(self, name) -> str:
        name = (name or "").strip()
        if not name:
            raise UserGroupValidationError("name is required")
        return name

    def _validate_parent_group(
        self, parent_group: Optional[str], *, current_slug: str
    ) -> None:
        if not parent_group:
            return
        if parent_group == current_slug:
            raise UserGroupValidationError("a group cannot be its own parent")
        if self._repository.find_by_slug(parent_group) is None:
            raise UserGroupValidationError(
                f"parent_group '{parent_group}' does not reference an existing group"
            )
