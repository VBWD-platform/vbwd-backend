"""S50.3 — invoice_extra_fields_registry contract tests.

A generic, domain-neutral registry: core routes the invoice through every
registered provider and merges the **opaque dicts** they return into the
invoice response, never interpreting a key. Mirrors
``deletion_dependency_registry`` (multi-provider, plugin-keyed).
"""
from unittest.mock import MagicMock

import pytest

from vbwd.services.invoice_extra_fields_registry import (
    aggregate_invoice_extra_fields,
    clear_invoice_extra_fields_providers,
    register_invoice_extra_fields_provider,
    unregister_invoice_extra_fields_provider,
)


@pytest.fixture(autouse=True)
def _isolate():
    clear_invoice_extra_fields_providers()
    yield
    clear_invoice_extra_fields_providers()


def test_aggregate_returns_empty_when_no_provider_registered():
    """Disabled-plugin path: invoice response carries only core fields."""
    assert aggregate_invoice_extra_fields(MagicMock()) == {}


def test_register_provider_then_aggregate_merges_its_opaque_dict():
    register_invoice_extra_fields_provider(
        "subscription", lambda invoice: {"plan_name": "Pro", "any_key": 1}
    )
    result = aggregate_invoice_extra_fields(MagicMock())
    assert result == {"plan_name": "Pro", "any_key": 1}


def test_multiple_providers_merge_into_one_dict():
    register_invoice_extra_fields_provider("a", lambda invoice: {"x": 1})
    register_invoice_extra_fields_provider("b", lambda invoice: {"y": 2})
    assert aggregate_invoice_extra_fields(MagicMock()) == {"x": 1, "y": 2}


def test_provider_returning_empty_dict_contributes_nothing():
    register_invoice_extra_fields_provider("a", lambda invoice: {})
    assert aggregate_invoice_extra_fields(MagicMock()) == {}


def test_unregister_removes_just_that_provider():
    register_invoice_extra_fields_provider("a", lambda invoice: {"x": 1})
    register_invoice_extra_fields_provider("b", lambda invoice: {"y": 2})
    unregister_invoice_extra_fields_provider("a")
    assert aggregate_invoice_extra_fields(MagicMock()) == {"y": 2}


def test_unregister_unknown_key_is_idempotent():
    unregister_invoice_extra_fields_provider("never-registered")


def test_clear_all_providers():
    register_invoice_extra_fields_provider("a", lambda invoice: {"x": 1})
    clear_invoice_extra_fields_providers()
    assert aggregate_invoice_extra_fields(MagicMock()) == {}


def test_double_register_same_key_replaces():
    register_invoice_extra_fields_provider("a", lambda invoice: {"x": "first"})
    register_invoice_extra_fields_provider("a", lambda invoice: {"x": "second"})
    assert aggregate_invoice_extra_fields(MagicMock()) == {"x": "second"}
