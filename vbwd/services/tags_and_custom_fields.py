"""Generic tags & custom-fields port (S77) — core-owned, by-id only.

Core owns the four tables (``vbwd_tag``, ``vbwd_entity_tag``,
``vbwd_custom_field_def``, ``vbwd_custom_field_value``), so the default
implementation IS the production implementation — there is no no-op fallback
(unlike ``entitlement``). Only the by-id (point-lookup) and by-id-batch paths
exist (D5/D6); catalog filtering/faceting is deliberately out of scope.

Consumers resolve the port from the DI container
(``container.tags_and_custom_fields()``) and never import the models. Every
method that takes an ``entity_type`` rejects an unregistered type with
``UnknownEntityTypeError`` so a disabled plugin's type stops being addressable.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from uuid import UUID


class UnknownEntityTypeError(ValueError):
    """Raised when an entity_type is not registered (entity_type_registry)."""


class UnknownCustomFieldError(ValueError):
    """Raised when a custom-field key has no def for the entity type."""


class CustomFieldValidationError(ValueError):
    """Raised when a value does not match its def's type / options."""


class ITagsAndCustomFields(ABC):
    """Narrow by-id port (ISP) — only the value-access seam (D4/D5/D6)."""

    # --- tags (free-form slugs, reusable across entity types) ---
    @abstractmethod
    def get_tags(self, entity_type: str, entity_id: UUID) -> List[str]:
        """Tag slugs attached to one entity."""

    @abstractmethod
    def get_tags_bulk(
        self, entity_type: str, entity_ids: List[UUID]
    ) -> Dict[UUID, List[str]]:
        """Tag slugs for a page of entities (one query, D6)."""

    @abstractmethod
    def set_tags(self, entity_type: str, entity_id: UUID, slugs: List[str]) -> None:
        """Replace the full tag set (idempotent); unknown slugs auto-created."""

    @abstractmethod
    def list_applicable_tags(self, entity_type: str) -> List[Dict]:
        """Catalog rows where parent_entity_type IS NULL OR = entity_type."""

    # --- custom fields (typed, defined per entity type) ---
    @abstractmethod
    def get_field_defs(self, entity_type: str) -> List[Dict]:
        """The schema: ``[{key,label,type,options,sort_order}, ...]``."""

    @abstractmethod
    def get_custom_fields(self, entity_type: str, entity_id: UUID) -> Dict[str, Any]:
        """Custom-field values for one entity."""

    @abstractmethod
    def get_custom_fields_bulk(
        self, entity_type: str, entity_ids: List[UUID]
    ) -> Dict[UUID, Dict[str, Any]]:
        """Custom-field values for a page of entities (one query, D6)."""

    @abstractmethod
    def set_custom_fields(
        self, entity_type: str, entity_id: UUID, values: Dict[str, Any]
    ) -> None:
        """Partial upsert of the given keys; ``None`` clears; validated."""


class _DefaultTagsAndCustomFields(ITagsAndCustomFields):
    """The production impl — core owns the tables (no no-op fallback).

    Delegates to ``TagService`` / ``CustomFieldService`` (built per call with a
    request-scoped session). The session factory is injected so the resolver can
    bind it to the live ``db.session`` without this module importing Flask.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _require_registered(self, entity_type: str) -> None:
        from vbwd.services.entity_type_registry import is_registered

        if not is_registered(entity_type):
            raise UnknownEntityTypeError(
                f"Entity type '{entity_type}' is not registered"
            )

    def _tag_service(self):
        from vbwd.repositories.entity_tag_repository import EntityTagRepository
        from vbwd.repositories.tag_repository import TagRepository
        from vbwd.services.tag_service import TagService

        session = self._session_factory()
        return TagService(
            tag_repo=TagRepository(session),
            entity_tag_repo=EntityTagRepository(session),
        )

    def _custom_field_service(self):
        from vbwd.repositories.custom_field_def_repository import (
            CustomFieldDefRepository,
        )
        from vbwd.repositories.custom_field_value_repository import (
            CustomFieldValueRepository,
        )
        from vbwd.services.custom_field_service import CustomFieldService

        session = self._session_factory()
        return CustomFieldService(
            def_repo=CustomFieldDefRepository(session),
            value_repo=CustomFieldValueRepository(session),
        )

    def get_tags(self, entity_type: str, entity_id: UUID) -> List[str]:
        self._require_registered(entity_type)
        return self._tag_service().get_tags(entity_type, entity_id)

    def get_tags_bulk(
        self, entity_type: str, entity_ids: List[UUID]
    ) -> Dict[UUID, List[str]]:
        self._require_registered(entity_type)
        return self._tag_service().get_tags_bulk(entity_type, entity_ids)

    def set_tags(self, entity_type: str, entity_id: UUID, slugs: List[str]) -> None:
        self._require_registered(entity_type)
        self._tag_service().set_tags(entity_type, entity_id, slugs)

    def list_applicable_tags(self, entity_type: str) -> List[Dict]:
        self._require_registered(entity_type)
        return self._tag_service().list_applicable_tags(entity_type)

    def get_field_defs(self, entity_type: str) -> List[Dict]:
        self._require_registered(entity_type)
        return self._custom_field_service().get_field_defs(entity_type)

    def get_custom_fields(self, entity_type: str, entity_id: UUID) -> Dict[str, Any]:
        self._require_registered(entity_type)
        return self._custom_field_service().get_custom_fields(entity_type, entity_id)

    def get_custom_fields_bulk(
        self, entity_type: str, entity_ids: List[UUID]
    ) -> Dict[UUID, Dict[str, Any]]:
        self._require_registered(entity_type)
        return self._custom_field_service().get_custom_fields_bulk(
            entity_type, entity_ids
        )

    def set_custom_fields(
        self, entity_type: str, entity_id: UUID, values: Dict[str, Any]
    ) -> None:
        self._require_registered(entity_type)
        self._custom_field_service().set_custom_fields(entity_type, entity_id, values)


_provider: Optional[ITagsAndCustomFields] = None


def register_tags_and_custom_fields(provider: ITagsAndCustomFields) -> None:
    """Override the port (rarely needed; core owns the default)."""
    global _provider
    _provider = provider


def clear_tags_and_custom_fields() -> None:
    """Reset to the core default (test teardown)."""
    global _provider
    _provider = None


def resolve_tags_and_custom_fields() -> ITagsAndCustomFields:
    """The registered provider, or the core default bound to ``db.session``."""
    if _provider is not None:
        return _provider

    def _session_factory():
        from vbwd.extensions import db

        return db.session

    return _DefaultTagsAndCustomFields(_session_factory)


def append_tags_and_custom_fields(
    data: Dict[str, Any], entity_type: str, entity_id: UUID
) -> Dict[str, Any]:
    """Attach ``tags`` + ``custom_fields`` to a serialised record (D4 helper).

    List serializers MUST use the ``*_bulk`` port variants instead (D6).
    """
    port = resolve_tags_and_custom_fields()
    data["tags"] = port.get_tags(entity_type, entity_id)
    data["custom_fields"] = port.get_custom_fields(entity_type, entity_id)
    return data
