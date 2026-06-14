"""S77 — tags & custom-fields port (resolve/register + helper + guards)."""
from uuid import uuid4

import pytest

from vbwd.services.entity_type_registry import (
    EntityTypeRegistration,
    clear_entity_types,
    register_entity_type,
)
from vbwd.services.tags_and_custom_fields import (
    ITagsAndCustomFields,
    UnknownEntityTypeError,
    _DefaultTagsAndCustomFields,
    append_tags_and_custom_fields,
    clear_tags_and_custom_fields,
    register_tags_and_custom_fields,
    resolve_tags_and_custom_fields,
)


@pytest.fixture(autouse=True)
def _clean():
    clear_tags_and_custom_fields()
    clear_entity_types()
    yield
    clear_tags_and_custom_fields()
    clear_entity_types()


class _FakePort(ITagsAndCustomFields):
    def get_tags(self, entity_type, entity_id):
        return ["alpha", "beta"]

    def get_tags_bulk(self, entity_type, entity_ids):
        return {entity_id: ["alpha"] for entity_id in entity_ids}

    def set_tags(self, entity_type, entity_id, slugs):
        pass

    def list_applicable_tags(self, entity_type):
        return []

    def get_field_defs(self, entity_type):
        return []

    def get_custom_fields(self, entity_type, entity_id):
        return {"color": "red"}

    def get_custom_fields_bulk(self, entity_type, entity_ids):
        return {entity_id: {} for entity_id in entity_ids}

    def set_custom_fields(self, entity_type, entity_id, values):
        pass


def test_resolve_returns_default_impl_when_none_registered():
    port = resolve_tags_and_custom_fields()
    assert isinstance(port, _DefaultTagsAndCustomFields)


def test_register_overrides_the_default():
    register_tags_and_custom_fields(_FakePort())
    assert isinstance(resolve_tags_and_custom_fields(), _FakePort)


def test_append_helper_attaches_tags_and_custom_fields():
    register_tags_and_custom_fields(_FakePort())
    entity_id = uuid4()

    enriched = append_tags_and_custom_fields({"id": str(entity_id)}, "user", entity_id)

    assert enriched["tags"] == ["alpha", "beta"]
    assert enriched["custom_fields"] == {"color": "red"}


def test_default_impl_rejects_unregistered_entity_type():
    port = resolve_tags_and_custom_fields()
    with pytest.raises(UnknownEntityTypeError):
        port.get_tags("never_registered", uuid4())


def test_default_impl_accepts_registered_type_guard_passes():
    # With the type registered, the guard passes; the call then needs a session,
    # which is exercised in the integration suite. Here we only assert the guard.
    register_entity_type(EntityTypeRegistration("user", "User", "users.manage"))
    port = resolve_tags_and_custom_fields()
    # No app context -> the session lookup raises, NOT UnknownEntityTypeError.
    with pytest.raises(Exception) as exc_info:
        port.list_applicable_tags("user")
    assert not isinstance(exc_info.value, UnknownEntityTypeError)
