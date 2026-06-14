"""Registry of addressable entity types for tags & custom fields (S77).

The tags / custom-fields framework is polymorphic, keyed by
``(entity_type, entity_id)`` where ``entity_type`` is a registered string
(e.g. ``"user"``, ``"shop_product"``). Only registered types are accepted, so a
disabled plugin's type stops being addressable and core names no plugin domain.

Core registers ``"user"`` at startup; plugins register their type(s) on enable
and unregister on disable. Mirrors ``deletion_dependency_registry`` /
``invoice_extra_fields_registry``: a module-level dict with register/resolve.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class EntityTypeRegistration:
    """A registered, taggable/custom-field-able entity type."""

    entity_type: str  # polymorphic key, e.g. "shop_product"
    label: str  # human label for the admin catalog UI
    manage_permission: str  # permission the value endpoints enforce on write


_registrations: Dict[str, EntityTypeRegistration] = {}


def register_entity_type(registration: EntityTypeRegistration) -> None:
    """Register (or replace) an entity type."""
    _registrations[registration.entity_type] = registration


def unregister_entity_type(entity_type: str) -> None:
    """Remove an entity type (plugin disable). No-op if absent."""
    _registrations.pop(entity_type, None)


def clear_entity_types() -> None:
    """Reset all registrations (test teardown)."""
    _registrations.clear()


def is_registered(entity_type: str) -> bool:
    """Whether the entity type is currently registered."""
    return entity_type in _registrations


def get_entity_type(entity_type: str) -> Optional[EntityTypeRegistration]:
    """The registration for ``entity_type``, or ``None`` if not registered."""
    return _registrations.get(entity_type)


def list_entity_types() -> List[EntityTypeRegistration]:
    """All registrations — drives the admin catalog type picker."""
    return list(_registrations.values())
