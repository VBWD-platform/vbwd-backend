"""Repository for the Tag catalog (S77)."""
from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from vbwd.models.tag import Tag
from vbwd.repositories.base import BaseRepository


class TagRepository(BaseRepository[Tag]):
    """Data access for ``vbwd_tag`` (catalog CRUD + applicable-tags query)."""

    def __init__(self, session: Session):
        super().__init__(session=session, model=Tag)

    def find_by_slug(self, slug: str) -> Optional[Tag]:
        """The tag with this (globally unique) slug, or None."""
        return self._session.query(Tag).filter_by(slug=slug).first()

    def find_by_slugs(self, slugs: List[str]) -> List[Tag]:
        """Tags for a set of slugs (batch, no N+1)."""
        if not slugs:
            return []
        return self._session.query(Tag).filter(Tag.slug.in_(slugs)).all()

    def list_catalog(self, parent_entity_type: Optional[str] = None) -> List[Tag]:
        """All catalog tags, optionally filtered by ``parent_entity_type``.

        Drives the admin catalog list (not the per-entity TagPicker, which uses
        :meth:`list_applicable`). Ordered by name for a stable admin view.
        """
        query = self._session.query(Tag)
        if parent_entity_type is not None:
            query = query.filter(Tag.parent_entity_type == parent_entity_type)
        return query.order_by(Tag.name).all()

    def list_applicable(self, entity_type: str) -> List[Tag]:
        """Tags applicable to ``entity_type``: global (NULL) or scoped to it."""
        return (
            self._session.query(Tag)
            .filter(
                or_(
                    Tag.parent_entity_type.is_(None),
                    Tag.parent_entity_type == entity_type,
                )
            )
            .order_by(Tag.name)
            .all()
        )

    def delete_by_slug(self, slug: str) -> bool:
        """Delete the tag (cascades ``entity_tag`` rows via the FK)."""
        tag = self.find_by_slug(slug)
        if tag is None:
            return False
        self._session.delete(tag)
        self._session.commit()
        return True
