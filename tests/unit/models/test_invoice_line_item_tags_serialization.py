"""S77 — invoice serializer appends each line's FROZEN tags/CF via bulk (D6).

``UserInvoice.to_dict()`` enriches each line dict with the snapshot tags/custom
fields stored on the ``invoice_line_item`` id. It uses the ``*_bulk`` port
variants so an N-line invoice fires exactly one tags query + one CF query — no
N+1. It reads the frozen copy, never the live source product.
"""
from uuid import uuid4

import pytest

from vbwd.models.enums import InvoiceStatus, LineItemType
from vbwd.models.invoice import UserInvoice
from vbwd.models.invoice_line_item import InvoiceLineItem
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


class _CountingBulkPort(ITagsAndCustomFields):
    def __init__(self, tags_by_id, fields_by_id):
        self._tags_by_id = tags_by_id
        self._fields_by_id = fields_by_id
        self.tags_bulk_calls = 0
        self.fields_bulk_calls = 0

    def get_tags(self, entity_type, entity_id):
        return self._tags_by_id.get(entity_id, [])

    def get_tags_bulk(self, entity_type, entity_ids):
        self.tags_bulk_calls += 1
        return {eid: self._tags_by_id.get(eid, []) for eid in entity_ids}

    def set_tags(self, entity_type, entity_id, slugs):
        pass

    def list_applicable_tags(self, entity_type):
        return []

    def get_field_defs(self, entity_type):
        return []

    def get_custom_fields(self, entity_type, entity_id):
        return self._fields_by_id.get(entity_id, {})

    def get_custom_fields_bulk(self, entity_type, entity_ids):
        self.fields_bulk_calls += 1
        return {eid: self._fields_by_id.get(eid, {}) for eid in entity_ids}

    def set_custom_fields(self, entity_type, entity_id, values):
        pass


def _line(line_id):
    line = InvoiceLineItem()
    line.id = line_id
    line.invoice_id = uuid4()
    line.item_type = LineItemType.CUSTOM
    line.item_id = uuid4()
    line.description = "Widget"
    line.quantity = 1
    line.unit_price = 10
    line.total_price = 10
    return line


@pytest.fixture(autouse=True)
def _clean():
    clear_tags_and_custom_fields()
    clear_entity_types()
    yield
    clear_tags_and_custom_fields()
    clear_entity_types()


def test_to_dict_appends_frozen_tags_and_fields_per_line_one_bulk_query_each():
    register_entity_type(
        EntityTypeRegistration(
            "invoice_line_item", "Invoice line item", "invoices.manage"
        )
    )
    line_one_id, line_two_id = uuid4(), uuid4()
    port = _CountingBulkPort(
        tags_by_id={line_one_id: ["sale"], line_two_id: ["clearance", "new"]},
        fields_by_id={line_one_id: {"warranty": 24}, line_two_id: {}},
    )
    register_tags_and_custom_fields(port)

    invoice = UserInvoice()
    invoice.id = uuid4()
    invoice.user_id = uuid4()
    invoice.invoice_number = "INV-TEST"
    invoice.amount = 20
    invoice.currency = "EUR"
    invoice.status = InvoiceStatus.PAID
    invoice.line_items = [_line(line_one_id), _line(line_two_id)]

    data = invoice.to_dict()

    lines = {item["id"]: item for item in data["line_items"]}
    assert lines[str(line_one_id)]["tags"] == ["sale"]
    assert lines[str(line_one_id)]["custom_fields"] == {"warranty": 24}
    assert lines[str(line_two_id)]["tags"] == ["clearance", "new"]
    assert lines[str(line_two_id)]["custom_fields"] == {}

    # D6: one bulk call each, regardless of line count
    assert port.tags_bulk_calls == 1
    assert port.fields_bulk_calls == 1


def test_to_dict_without_invoice_line_item_type_registered_still_serializes():
    # invoice_line_item not registered (e.g. framework path disabled): the
    # serializer must not blow up; lines simply carry empty tags/CF.
    line_id = uuid4()
    invoice = UserInvoice()
    invoice.id = uuid4()
    invoice.user_id = uuid4()
    invoice.invoice_number = "INV-TEST2"
    invoice.amount = 10
    invoice.currency = "EUR"
    invoice.status = InvoiceStatus.PAID
    invoice.line_items = [_line(line_id)]

    data = invoice.to_dict()
    line = data["line_items"][0]
    assert line["tags"] == []
    assert line["custom_fields"] == {}
