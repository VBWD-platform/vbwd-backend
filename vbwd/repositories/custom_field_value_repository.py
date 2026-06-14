"""Repository for custom-field values (S77)."""
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

from vbwd.models.custom_field_value import CustomFieldValue


class CustomFieldValueRepository:
    """Data access for ``vbwd_custom_field_value`` — by-id reads + upsert (D5/D6)."""

    def __init__(self, session: Session):
        self._session = session

    def get_values(self, entity_type: str, entity_id: UUID) -> Dict[str, Any]:
        """All custom-field values for one entity, as ``{field_key: value}``."""
        rows = (
            self._session.query(CustomFieldValue)
            .filter(
                CustomFieldValue.entity_type == entity_type,
                CustomFieldValue.entity_id == entity_id,
            )
            .all()
        )
        return {row.field_key: row.value for row in rows}

    def get_values_bulk(
        self, entity_type: str, entity_ids: List[UUID]
    ) -> Dict[UUID, Dict[str, Any]]:
        """Values for a page of entities in one query (no N+1, D6)."""
        result: Dict[UUID, Dict[str, Any]] = {entity_id: {} for entity_id in entity_ids}
        if not entity_ids:
            return result
        rows = (
            self._session.query(CustomFieldValue)
            .filter(
                CustomFieldValue.entity_type == entity_type,
                CustomFieldValue.entity_id.in_(entity_ids),
            )
            .all()
        )
        for row in rows:
            result.setdefault(row.entity_id, {})[row.field_key] = row.value
        return result

    def upsert(
        self, entity_type: str, entity_id: UUID, field_key: str, value: Any
    ) -> None:
        """Insert or update one field value (no commit — batched by caller)."""
        existing = self._session.get(
            CustomFieldValue, (entity_type, entity_id, field_key)
        )
        if existing is None:
            self._session.add(
                CustomFieldValue(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    field_key=field_key,
                    value=value,
                )
            )
        else:
            existing.value = value

    def delete(self, entity_type: str, entity_id: UUID, field_key: str) -> None:
        """Remove one field value (no commit — batched by caller)."""
        self._session.query(CustomFieldValue).filter(
            CustomFieldValue.entity_type == entity_type,
            CustomFieldValue.entity_id == entity_id,
            CustomFieldValue.field_key == field_key,
        ).delete(synchronize_session=False)

    def commit(self) -> None:
        """Persist batched upserts/deletes."""
        self._session.commit()
