"""Custom-field definition model (S77).

Defines a typed attribute for an entity type. ``key`` is unique per
``entity_type``. Values (in ``custom_field_value``) are validated against this
def's ``type`` / ``options`` on write.
"""
from sqlalchemy.dialects.postgresql import JSONB

from vbwd.extensions import db
from vbwd.models.base import BaseModel

# The supported field types (D3). ``options`` is required for select/multiselect.
CUSTOM_FIELD_TYPES = ("text", "number", "bool", "date", "select", "multiselect")


class CustomFieldDef(BaseModel):
    """A typed custom-field definition for one entity type."""

    __tablename__ = "vbwd_custom_field_def"
    __table_args__ = (
        db.UniqueConstraint(
            "entity_type", "key", name="uq_vbwd_custom_field_def_entity_key"
        ),
    )

    entity_type = db.Column(db.String(64), nullable=False, index=True)
    key = db.Column(db.String(255), nullable=False)
    label = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(32), nullable=False)
    options = db.Column(JSONB, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self) -> dict:
        """Serialise the def (the schema row consumed by editors)."""
        return {
            "id": str(self.id),
            "entity_type": self.entity_type,
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "options": self.options,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
