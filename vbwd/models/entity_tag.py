"""Entity-tag link table (S77) — the polymorphic M2M.

Links a tag (by ``tag_slug``) to any ``(entity_type, entity_id)``. Composite
primary key ``(entity_type, entity_id, tag_slug)`` serves "tags of this entity";
the reverse index ``(tag_slug, entity_type, entity_id)`` serves "entities with
tag X" (admin stats/export) as an index range, not a scan (D6).

A plain ``db.Model`` link table — NOT ``BaseModel`` (no surrogate id / version).
"""
from sqlalchemy.dialects.postgresql import UUID

from vbwd.extensions import db


class EntityTag(db.Model):  # type: ignore[name-defined]
    """One ``(entity_type, entity_id) -> tag_slug`` association."""

    __tablename__ = "vbwd_entity_tag"
    __table_args__ = (
        db.Index(
            "ix_vbwd_entity_tag_reverse",
            "tag_slug",
            "entity_type",
            "entity_id",
        ),
    )

    entity_type = db.Column(db.String(64), primary_key=True, nullable=False)
    entity_id = db.Column(UUID(as_uuid=True), primary_key=True, nullable=False)
    tag_slug = db.Column(
        db.String(255),
        db.ForeignKey("vbwd_tag.slug", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
