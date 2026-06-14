"""Custom-field def CRUD + value validation/access service (S77).

Defs are typed per entity type; values are validated against the def's
``type`` / ``options`` on write. ``set_custom_fields`` is a partial upsert
(``None`` clears a field). Reads are by-id only (D5) with a bulk variant (D6).
"""
from datetime import date
from typing import Any, Dict, List, Optional, cast
from uuid import UUID

from vbwd.models.custom_field_def import CUSTOM_FIELD_TYPES, CustomFieldDef
from vbwd.repositories.custom_field_def_repository import CustomFieldDefRepository
from vbwd.repositories.custom_field_value_repository import (
    CustomFieldValueRepository,
)
from vbwd.services.tags_and_custom_fields import (
    CustomFieldValidationError,
    UnknownCustomFieldError,
)


class CustomFieldService:
    """Def CRUD + value get/set with per-type validation."""

    def __init__(
        self,
        def_repo: CustomFieldDefRepository,
        value_repo: CustomFieldValueRepository,
    ):
        self._def_repo = def_repo
        self._value_repo = value_repo

    # --- def CRUD ---
    def create_def(
        self,
        entity_type: str,
        key: str,
        label: str,
        field_type: str,
        options: Optional[List[str]] = None,
        sort_order: int = 0,
        is_active: bool = True,
    ) -> CustomFieldDef:
        """Create a custom-field definition."""
        if field_type not in CUSTOM_FIELD_TYPES:
            raise CustomFieldValidationError(
                f"Unsupported custom-field type '{field_type}'"
            )
        if field_type in ("select", "multiselect") and not options:
            raise CustomFieldValidationError(
                f"Type '{field_type}' requires non-empty options"
            )
        definition = CustomFieldDef(
            entity_type=entity_type,
            key=key,
            label=label,
            type=field_type,
            options=options,
            sort_order=sort_order,
            is_active=is_active,
        )
        return self._def_repo.save(definition)

    def update_def(
        self, entity_type: str, key: str, **changes
    ) -> Optional[CustomFieldDef]:
        """Update a def's mutable fields."""
        definition = self._def_repo.find_by_entity_type_and_key(entity_type, key)
        if definition is None:
            return None
        for field in ("label", "type", "options", "sort_order", "is_active"):
            if field in changes:
                setattr(definition, field, changes[field])
        return self._def_repo.save(definition)

    def update_def_by_id(self, def_id: UUID, **changes) -> Optional[CustomFieldDef]:
        """Update a def's mutable fields by primary id (admin route)."""
        definition = self._def_repo.find_by_id(def_id)
        if definition is None:
            return None
        for field in ("label", "type", "options", "sort_order", "is_active"):
            if field in changes:
                setattr(definition, field, changes[field])
        return self._def_repo.save(definition)

    def delete_def_by_id(self, def_id: UUID) -> bool:
        """Delete a def by primary id (admin route). Its values are orphaned."""
        return self._def_repo.delete(def_id)

    def delete_def(self, entity_type: str, key: str) -> bool:
        """Delete a def (its values are removed alongside)."""
        definition = self._def_repo.find_by_entity_type_and_key(entity_type, key)
        if definition is None:
            return False
        self._def_repo.delete(cast(UUID, definition.id))
        return True

    def get_field_defs(self, entity_type: str) -> List[Dict]:
        """The active schema for an entity type (ordered)."""
        return [
            definition.to_dict()
            for definition in self._def_repo.list_for_entity_type(entity_type)
        ]

    def list_defs(
        self,
        entity_type: Optional[str] = None,
        field_type: Optional[str] = None,
    ) -> List[Dict]:
        """The whole def catalog (admin list), optionally filtered.

        Unlike :meth:`get_field_defs` (active-only schema for one entity type),
        this lists every def — active and inactive — for the catalog manager,
        filtered by ``entity_type`` and/or ``field_type``.
        """
        return [
            definition.to_dict()
            for definition in self._def_repo.list_catalog(
                entity_type=entity_type, field_type=field_type
            )
        ]

    def get_def(self, def_id: UUID) -> Optional[Dict]:
        """A single def by primary id (admin detail), or None."""
        definition = self._def_repo.find_by_id(def_id)
        return definition.to_dict() if definition is not None else None

    # --- value get / set ---
    def get_custom_fields(self, entity_type: str, entity_id: UUID) -> Dict[str, Any]:
        """Custom-field values for one entity."""
        return self._value_repo.get_values(entity_type, entity_id)

    def get_custom_fields_bulk(
        self, entity_type: str, entity_ids: List[UUID]
    ) -> Dict[UUID, Dict[str, Any]]:
        """Custom-field values for a page of entities (no N+1)."""
        return self._value_repo.get_values_bulk(entity_type, entity_ids)

    def set_custom_fields(
        self, entity_type: str, entity_id: UUID, values: Dict[str, Any]
    ) -> None:
        """Partial upsert of the given keys; ``None`` clears; validated."""
        for key, value in values.items():
            definition = self._def_repo.find_by_entity_type_and_key(entity_type, key)
            if definition is None:
                raise UnknownCustomFieldError(
                    f"No custom field '{key}' for entity type '{entity_type}'"
                )
            self.validate_value(definition, value)
            if value is None:
                self._value_repo.delete(entity_type, entity_id, key)
            else:
                self._value_repo.upsert(entity_type, entity_id, key, value)
        self._value_repo.commit()

    # --- validation ---
    def validate_value(self, definition: CustomFieldDef, value: Any) -> None:
        """Validate ``value`` against the def's type/options. ``None`` clears."""
        if value is None:
            return
        validators = {
            "text": self._validate_text,
            "number": self._validate_number,
            "bool": self._validate_bool,
            "date": self._validate_date,
            "select": self._validate_select,
            "multiselect": self._validate_multiselect,
        }
        validator = validators.get(definition.type)
        if validator is None:
            raise CustomFieldValidationError(
                f"Unsupported custom-field type '{definition.type}'"
            )
        validator(definition, value)

    def _validate_text(self, definition: CustomFieldDef, value: Any) -> None:
        if not isinstance(value, str):
            raise CustomFieldValidationError(
                f"Field '{definition.key}' expects text (str)"
            )

    def _validate_number(self, definition: CustomFieldDef, value: Any) -> None:
        # bool is a subclass of int — reject it explicitly.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CustomFieldValidationError(
                f"Field '{definition.key}' expects a number"
            )

    def _validate_bool(self, definition: CustomFieldDef, value: Any) -> None:
        if not isinstance(value, bool):
            raise CustomFieldValidationError(
                f"Field '{definition.key}' expects a boolean"
            )

    def _validate_date(self, definition: CustomFieldDef, value: Any) -> None:
        if not isinstance(value, str):
            raise CustomFieldValidationError(
                f"Field '{definition.key}' expects an ISO date string"
            )
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise CustomFieldValidationError(
                f"Field '{definition.key}' expects an ISO date (YYYY-MM-DD)"
            ) from error

    def _validate_select(self, definition: CustomFieldDef, value: Any) -> None:
        options = definition.options or []
        if value not in options:
            raise CustomFieldValidationError(
                f"Field '{definition.key}' value must be one of {options}"
            )

    def _validate_multiselect(self, definition: CustomFieldDef, value: Any) -> None:
        options = definition.options or []
        if not isinstance(value, list):
            raise CustomFieldValidationError(f"Field '{definition.key}' expects a list")
        invalid = [item for item in value if item not in options]
        if invalid:
            raise CustomFieldValidationError(
                f"Field '{definition.key}' has invalid values {invalid}"
            )
