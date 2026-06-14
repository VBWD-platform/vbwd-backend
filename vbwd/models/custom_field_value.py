"""Custom-field value model (S77) — the EAV value row.

Stores one field's value for one entity. Composite primary key
``(entity_type, entity_id, field_key)`` serves "fields of this entity" + point
reads (D5). A plain ``db.Model`` (NOT ``BaseModel``); ``value`` is JSON so a
single column holds every field type.
"""
from sqlalchemy.dialects.postgresql import JSONB, UUID

from vbwd.extensions import db


class CustomFieldValue(db.Model):  # type: ignore[name-defined]
    """One custom-field value for a ``(entity_type, entity_id)``."""

    __tablename__ = "vbwd_custom_field_value"

    entity_type = db.Column(db.String(64), primary_key=True, nullable=False)
    entity_id = db.Column(UUID(as_uuid=True), primary_key=True, nullable=False)
    field_key = db.Column(db.String(255), primary_key=True, nullable=False)
    value = db.Column(JSONB, nullable=True)
