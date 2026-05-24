"""S1 — catalog-item-id resolution moved off core into the registry.

Characterises the behaviour contract (item_type → catalog id) and pins the
agnosticism win: core `invoice_line_item` no longer knows subscription.
"""
import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from vbwd.events.line_item_registry import (
    ILineItemHandler,
    LineItemHandlerRegistry,
)
from vbwd.models.enums import LineItemType
from vbwd.models.invoice_line_item import InvoiceLineItem


class _FakeOwner(ILineItemHandler):
    """Owns one item type, returns a fixed catalog id for it."""

    def __init__(self, owned_type, catalog_id):
        self._owned_type = owned_type
        self._catalog_id = catalog_id

    def can_handle_line_item(self, line_item, context):
        return line_item.item_type == self._owned_type

    def activate_line_item(self, line_item, context):  # pragma: no cover
        ...

    def reverse_line_item(self, line_item, context):  # pragma: no cover
        ...

    def restore_line_item(self, line_item, context):  # pragma: no cover
        ...

    def resolve_catalog_item_id(self, line_item):
        if line_item.item_type != self._owned_type:
            return None
        return self._catalog_id


def _line_item(item_type):
    # Plain stub — handlers only read .item_type / .item_id; constructing a
    # MagicMock(spec=InvoiceLineItem) would introspect the ORM model and need
    # an app context.
    return SimpleNamespace(item_type=item_type, item_id=uuid4())


def test_registry_returns_first_owning_handler_result():
    registry = LineItemHandlerRegistry()
    registry.register(_FakeOwner(LineItemType.TOKEN_BUNDLE, "bundle-cat"))
    registry.register(_FakeOwner(LineItemType.SUBSCRIPTION, "plan-cat"))

    assert (
        registry.resolve_catalog_item_id(_line_item(LineItemType.SUBSCRIPTION))
        == "plan-cat"
    )
    assert (
        registry.resolve_catalog_item_id(_line_item(LineItemType.TOKEN_BUNDLE))
        == "bundle-cat"
    )


def test_registry_returns_none_when_no_handler_owns_the_type():
    """Plugin-disabled analogue: subscription handler absent ⇒ None, no error."""
    registry = LineItemHandlerRegistry()
    registry.register(_FakeOwner(LineItemType.TOKEN_BUNDLE, "bundle-cat"))

    assert (
        registry.resolve_catalog_item_id(_line_item(LineItemType.SUBSCRIPTION)) is None
    )


def test_default_handler_resolve_is_none():
    """ISP: handlers without a catalog mapping inherit the None default."""

    class _NoCatalog(_FakeOwner):
        resolve_catalog_item_id = ILineItemHandler.resolve_catalog_item_id

    handler = _NoCatalog(LineItemType.TOKEN_BUNDLE, "x")
    assert (
        handler.resolve_catalog_item_id(_line_item(LineItemType.TOKEN_BUNDLE)) is None
    )


def test_core_invoice_line_item_has_no_subscription_knowledge():
    """Core model must not import or branch on subscription/addon types."""
    source = inspect.getsource(InvoiceLineItem._resolve_catalog_item_id)
    assert "Subscription" not in source
    assert "AddOnSubscription" not in source
    assert "line_item_registry" in source


def test_core_token_bundle_handler_resolves_only_its_type():
    from vbwd.handlers.core_line_item_handler import CoreLineItemHandler

    handler = CoreLineItemHandler(container=MagicMock())
    # Not its type → None without touching the DB.
    assert (
        handler.resolve_catalog_item_id(_line_item(LineItemType.SUBSCRIPTION)) is None
    )
