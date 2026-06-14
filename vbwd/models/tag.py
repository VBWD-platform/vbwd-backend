"""Tag catalog model (S77).

A ``Tag`` is a generic, cross-entity label. ``slug`` is the GLOBALLY unique
identity (the same slug is reused across entity types). ``parent_entity_type``
scopes where the tag may be applied: ``NULL`` = global (any entity type),
non-null = that type only (drives the TagPicker's applicable-tags list).
"""
from sqlalchemy.dialects.postgresql import JSONB

from vbwd.extensions import db
from vbwd.models.base import BaseModel


class Tag(BaseModel):
    """A reusable, slug-addressed tag in the single core catalog."""

    __tablename__ = "vbwd_tag"

    slug = db.Column(db.String(255), nullable=False, unique=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    parent_entity_type = db.Column(db.String(64), nullable=True)
    meta_data = db.Column(JSONB, nullable=False, default=dict)
    color = db.Column(db.String(32), nullable=True)

    def to_dict(self) -> dict:
        """Serialise the catalog row (timestamps as ISO strings)."""
        return {
            "id": str(self.id),
            "slug": self.slug,
            "name": self.name,
            "parent_entity_type": self.parent_entity_type,
            "meta_data": self.meta_data or {},
            "color": self.color,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
