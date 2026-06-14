"""Repository for the entity-tag link table (S77)."""
from typing import Dict, List
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from vbwd.models.entity_tag import EntityTag


class EntityTagRepository:
    """Data access for ``vbwd_entity_tag`` — by-id reads + stats (D5/D6)."""

    def __init__(self, session: Session):
        self._session = session

    def list_slugs(self, entity_type: str, entity_id: UUID) -> List[str]:
        """Tag slugs attached to one entity."""
        rows = (
            self._session.query(EntityTag.tag_slug)
            .filter(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id == entity_id,
            )
            .all()
        )
        return [row[0] for row in rows]

    def list_slugs_bulk(
        self, entity_type: str, entity_ids: List[UUID]
    ) -> Dict[UUID, List[str]]:
        """Tag slugs for a page of entities in one query (no N+1, D6)."""
        result: Dict[UUID, List[str]] = {entity_id: [] for entity_id in entity_ids}
        if not entity_ids:
            return result
        rows = (
            self._session.query(EntityTag.entity_id, EntityTag.tag_slug)
            .filter(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id.in_(entity_ids),
            )
            .all()
        )
        for entity_id, tag_slug in rows:
            result.setdefault(entity_id, []).append(tag_slug)
        return result

    def replace(self, entity_type: str, entity_id: UUID, slugs: List[str]) -> None:
        """Replace the full set of tags for one entity (idempotent)."""
        self._session.query(EntityTag).filter(
            EntityTag.entity_type == entity_type,
            EntityTag.entity_id == entity_id,
        ).delete(synchronize_session=False)
        for slug in dict.fromkeys(slugs):  # de-dup, preserve order
            self._session.add(
                EntityTag(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    tag_slug=slug,
                )
            )
        self._session.commit()

    def count_for_slug(self, slug: str) -> int:
        """Usage count for one tag slug across every entity."""
        return self._session.query(EntityTag).filter(EntityTag.tag_slug == slug).count()

    def count_for_slugs(self, slugs: List[str]) -> Dict[str, int]:
        """Usage counts for many slugs in ONE grouped query (D6 reverse index)."""
        result: Dict[str, int] = {slug: 0 for slug in slugs}
        if not slugs:
            return result
        rows = (
            self._session.query(EntityTag.tag_slug, func.count().label("usage_count"))
            .filter(EntityTag.tag_slug.in_(slugs))
            .group_by(EntityTag.tag_slug)
            .all()
        )
        for tag_slug, usage_count in rows:
            result[tag_slug] = usage_count
        return result
