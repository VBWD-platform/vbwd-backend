"""S77 — invoice line-item tags/CF snapshot at creation (core, agnostic).

At line-item creation the issuer freezes a copy of the *source* item's tags &
custom fields onto the ``invoice_line_item`` id, so a later change to the source
product/plan never mutates the historical invoice. The copy is a pure
``(entity_type, id)`` value copy through the core port — no plugin import.
"""
from uuid import uuid4

import pytest

from vbwd.events.line_item_registry import line_item_registry
from vbwd.services.entity_type_registry import (
    EntityTypeRegistration,
    clear_entity_types,
    register_entity_type,
)
from vbwd.services.tags_and_custom_fields import (
    ITagsAndCustomFields,
    clear_tags_and_custom_fields,
    register_tags_and_custom_fields,
)
from vbwd.services.invoice_line_item_snapshot import (
    snapshot_line_item_tags_and_custom_fields,
)


class _FakeLineItem:
    def __init__(self, line_id):
        self.id = line_id


class _RecordingPort(ITagsAndCustomFields):
    """A fake port that records writes and serves a fixed source snapshot."""

    def __init__(self, source_tags, source_fields):
        self._source_tags = source_tags
        self._source_fields = source_fields
        self.set_tags_calls = []
        self.set_fields_calls = []

    def get_tags(self, entity_type, entity_id):
        if entity_type == "invoice_line_item":
            return []
        return list(self._source_tags)

    def get_tags_bulk(self, entity_type, entity_ids):
        return {entity_id: [] for entity_id in entity_ids}

    def set_tags(self, entity_type, entity_id, slugs):
        self.set_tags_calls.append((entity_type, entity_id, slugs))

    def list_applicable_tags(self, entity_type):
        return []

    def get_field_defs(self, entity_type):
        return []

    def get_custom_fields(self, entity_type, entity_id):
        if entity_type == "invoice_line_item":
            return {}
        return dict(self._source_fields)

    def get_custom_fields_bulk(self, entity_type, entity_ids):
        return {entity_id: {} for entity_id in entity_ids}

    def set_custom_fields(self, entity_type, entity_id, values):
        self.set_fields_calls.append((entity_type, entity_id, values))


@pytest.fixture(autouse=True)
def _clean():
    clear_tags_and_custom_fields()
    clear_entity_types()
    line_item_registry.clear()
    yield
    clear_tags_and_custom_fields()
    clear_entity_types()
    line_item_registry.clear()


def _register_source_ref(entity_type, catalog_id):
    """Make the registry resolve every line item to one source ref."""
    from vbwd.events.line_item_registry import ILineItemHandler, LineItemResult

    class _Handler(ILineItemHandler):
        def can_handle_line_item(self, line_item, context):
            return False

        def activate_line_item(self, line_item, context):
            return LineItemResult.skip()

        def reverse_line_item(self, line_item, context):
            return LineItemResult.skip()

        def restore_line_item(self, line_item, context):
            return LineItemResult.skip()

        def resolve_catalog_entity_ref(self, line_item):
            return (entity_type, catalog_id)

    line_item_registry.register(_Handler())


def test_snapshot_copies_source_tags_and_fields_onto_line():
    register_entity_type(
        EntityTypeRegistration(
            "invoice_line_item", "Invoice line item", "invoices.manage"
        )
    )
    register_entity_type(
        EntityTypeRegistration("shop_product", "Product", "shop.products.manage")
    )
    catalog_id = str(uuid4())
    _register_source_ref("shop_product", catalog_id)
    port = _RecordingPort(source_tags=["sale", "new"], source_fields={"warranty": 24})
    register_tags_and_custom_fields(port)

    line = _FakeLineItem(uuid4())
    snapshot_line_item_tags_and_custom_fields(line)

    assert port.set_tags_calls == [("invoice_line_item", line.id, ["sale", "new"])]
    assert port.set_fields_calls == [("invoice_line_item", line.id, {"warranty": 24})]


def test_snapshot_noop_when_line_has_no_source_ref():
    register_entity_type(
        EntityTypeRegistration(
            "invoice_line_item", "Invoice line item", "invoices.manage"
        )
    )
    # no handler registered -> registry resolves no ref
    port = _RecordingPort(source_tags=["x"], source_fields={"k": "v"})
    register_tags_and_custom_fields(port)

    snapshot_line_item_tags_and_custom_fields(_FakeLineItem(uuid4()))

    assert port.set_tags_calls == []
    assert port.set_fields_calls == []


def test_snapshot_noop_when_source_has_no_tags_or_fields():
    register_entity_type(
        EntityTypeRegistration(
            "invoice_line_item", "Invoice line item", "invoices.manage"
        )
    )
    register_entity_type(
        EntityTypeRegistration("shop_product", "Product", "shop.products.manage")
    )
    _register_source_ref("shop_product", str(uuid4()))
    port = _RecordingPort(source_tags=[], source_fields={})
    register_tags_and_custom_fields(port)

    snapshot_line_item_tags_and_custom_fields(_FakeLineItem(uuid4()))

    # nothing to freeze -> no writes
    assert port.set_tags_calls == []
    assert port.set_fields_calls == []
