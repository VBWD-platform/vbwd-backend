"""Tag catalog + attach/detach service (S77).

Owns the ``vbwd_tag`` catalog (create/update/delete) and the by-id attach
(``set_tags``) / read (``get_tags``) paths, plus usage stats for the admin
list. Deleting a tag cascades its ``entity_tag`` rows via the FK.
"""
from typing import Dict, List, Optional
from uuid import UUID

from vbwd.models.tag import Tag
from vbwd.repositories.entity_tag_repository import EntityTagRepository
from vbwd.repositories.tag_repository import TagRepository


class TagService:
    """Catalog CRUD + by-id tag access + usage stats."""

    def __init__(self, tag_repo: TagRepository, entity_tag_repo: EntityTagRepository):
        self._tag_repo = tag_repo
        self._entity_tag_repo = entity_tag_repo

    # --- catalog CRUD ---
    def create_tag(
        self,
        slug: str,
        name: str,
        parent_entity_type: Optional[str] = None,
        meta_data: Optional[Dict] = None,
        color: Optional[str] = None,
    ) -> Tag:
        """Create a catalog tag."""
        tag = Tag(
            slug=slug,
            name=name,
            parent_entity_type=parent_entity_type,
            meta_data=meta_data or {},
            color=color,
        )
        return self._tag_repo.save(tag)

    def update_tag(self, slug: str, **changes) -> Optional[Tag]:
        """Update a catalog tag's mutable fields (name, parent, meta, color)."""
        tag = self._tag_repo.find_by_slug(slug)
        if tag is None:
            return None
        for field in ("name", "parent_entity_type", "meta_data", "color"):
            if field in changes:
                setattr(tag, field, changes[field])
        return self._tag_repo.save(tag)

    def delete_tag(self, slug: str) -> bool:
        """Delete a catalog tag (cascades its ``entity_tag`` rows via the FK)."""
        return self._tag_repo.delete_by_slug(slug)

    def list_applicable_tags(self, entity_type: str) -> List[Dict]:
        """Catalog rows applicable to ``entity_type`` (global or scoped)."""
        return [tag.to_dict() for tag in self._tag_repo.list_applicable(entity_type)]

    def list_tags(self, parent_entity_type: Optional[str] = None) -> List[Dict]:
        """The whole catalog (admin list), optionally scoped by parent type."""
        return [
            tag.to_dict()
            for tag in self._tag_repo.list_catalog(
                parent_entity_type=parent_entity_type
            )
        ]

    def list_tags_with_stats(
        self, parent_entity_type: Optional[str] = None
    ) -> List[Dict]:
        """Catalog rows each carrying a usage ``stats`` count (admin list).

        Stats are computed for the whole returned page in ONE grouped query via
        :meth:`get_stats_bulk` (the D6 reverse index) — never one query per row.
        """
        tags = self.list_tags(parent_entity_type=parent_entity_type)
        stats = self.get_stats_bulk([tag["slug"] for tag in tags])
        for tag in tags:
            tag["stats"] = stats.get(tag["slug"], 0)
        return tags

    # --- by-id attach / read ---
    def get_tags(self, entity_type: str, entity_id: UUID) -> List[str]:
        """Tag slugs attached to one entity."""
        return self._entity_tag_repo.list_slugs(entity_type, entity_id)

    def get_tags_bulk(
        self, entity_type: str, entity_ids: List[UUID]
    ) -> Dict[UUID, List[str]]:
        """Tag slugs for a page of entities (no N+1)."""
        return self._entity_tag_repo.list_slugs_bulk(entity_type, entity_ids)

    def set_tags(self, entity_type: str, entity_id: UUID, slugs: List[str]) -> None:
        """Replace the full tag set; unknown slugs are auto-created as global."""
        self._ensure_catalog_tags(slugs)
        self._entity_tag_repo.replace(entity_type, entity_id, slugs)

    def _ensure_catalog_tags(self, slugs: List[str]) -> None:
        """Auto-create any unknown slugs as global (parent_entity_type=NULL)."""
        if not slugs:
            return
        existing = {tag.slug for tag in self._tag_repo.find_by_slugs(list(slugs))}
        for slug in dict.fromkeys(slugs):
            if slug not in existing:
                self.create_tag(slug=slug, name=slug, parent_entity_type=None)

    # --- usage stats (admin list; off the hot per-entity port) ---
    def get_stats(self, slug: str) -> int:
        """Usage count for one tag slug across every entity."""
        return self._entity_tag_repo.count_for_slug(slug)

    def get_stats_bulk(self, slugs: List[str]) -> Dict[str, int]:
        """Usage counts for many slugs in ONE grouped COUNT (no N+1, D6)."""
        return self._entity_tag_repo.count_for_slugs(slugs)
