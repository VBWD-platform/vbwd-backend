"""S77 — entity-type registry (core seam, mirrors deletion_dependency_registry).

Only registered entity types are addressable by the tags/custom-fields port, so
a disabled plugin's type stops being accepted and core hard-codes no plugin
domain. Core registers ``user`` at startup; plugins register/unregister theirs.
"""
import pytest

from vbwd.services.entity_type_registry import (
    EntityTypeRegistration,
    clear_entity_types,
    get_entity_type,
    is_registered,
    list_entity_types,
    register_entity_type,
    unregister_entity_type,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_entity_types()
    yield
    clear_entity_types()


def test_register_and_resolve_entity_type():
    registration = EntityTypeRegistration("shop_product", "Product", "shop.manage")
    register_entity_type(registration)

    assert is_registered("shop_product") is True
    assert get_entity_type("shop_product") is registration


def test_unregistered_type_is_not_registered():
    assert is_registered("shop_product") is False
    assert get_entity_type("shop_product") is None


def test_unregister_removes_the_type():
    register_entity_type(
        EntityTypeRegistration("shop_product", "Product", "shop.manage")
    )
    unregister_entity_type("shop_product")

    assert is_registered("shop_product") is False


def test_unregister_unknown_type_is_a_noop():
    unregister_entity_type("never_registered")  # must not raise


def test_register_replaces_a_prior_registration_for_the_same_type():
    register_entity_type(EntityTypeRegistration("user", "User", "old.perm"))
    register_entity_type(EntityTypeRegistration("user", "User", "users.manage"))

    assert get_entity_type("user").manage_permission == "users.manage"
    assert len(list_entity_types()) == 1


def test_list_entity_types_returns_all_registrations():
    register_entity_type(EntityTypeRegistration("user", "User", "users.manage"))
    register_entity_type(
        EntityTypeRegistration("shop_product", "Product", "shop.manage")
    )

    types = {registration.entity_type for registration in list_entity_types()}
    assert types == {"user", "shop_product"}


def test_registration_is_frozen():
    registration = EntityTypeRegistration("user", "User", "users.manage")
    with pytest.raises(Exception):
        registration.entity_type = "other"  # type: ignore[misc]
