"""Repository for custom-field definitions (S77)."""
from typing import List, Optional

from sqlalchemy.orm import Session

from vbwd.models.custom_field_def import CustomFieldDef
from vbwd.repositories.base import BaseRepository


class CustomFieldDefRepository(BaseRepository[CustomFieldDef]):
    """Data access for ``vbwd_custom_field_def``."""

    def __init__(self, session: Session):
        super().__init__(session=session, model=CustomFieldDef)

    def list_for_entity_type(
        self, entity_type: str, active_only: bool = True
    ) -> List[CustomFieldDef]:
        """Defs for one entity type, ordered by ``sort_order`` then ``key``."""
        query = self._session.query(CustomFieldDef).filter(
            CustomFieldDef.entity_type == entity_type
        )
        if active_only:
            query = query.filter(CustomFieldDef.is_active.is_(True))
        return query.order_by(CustomFieldDef.sort_order, CustomFieldDef.key).all()

    def list_catalog(
        self,
        entity_type: Optional[str] = None,
        field_type: Optional[str] = None,
    ) -> List[CustomFieldDef]:
        """All defs (active and inactive), optionally filtered.

        Drives the admin catalog list. Filters by ``entity_type`` and/or
        ``field_type`` (the def's ``type``); unfiltered returns every def.
        Ordered by entity type, sort order, then key for a stable admin view.
        """
        query = self._session.query(CustomFieldDef)
        if entity_type is not None:
            query = query.filter(CustomFieldDef.entity_type == entity_type)
        if field_type is not None:
            query = query.filter(CustomFieldDef.type == field_type)
        return query.order_by(
            CustomFieldDef.entity_type,
            CustomFieldDef.sort_order,
            CustomFieldDef.key,
        ).all()

    def find_by_entity_type_and_key(
        self, entity_type: str, key: str
    ) -> Optional[CustomFieldDef]:
        """The def for ``(entity_type, key)``, or None."""
        return (
            self._session.query(CustomFieldDef)
            .filter(
                CustomFieldDef.entity_type == entity_type,
                CustomFieldDef.key == key,
            )
            .first()
        )
