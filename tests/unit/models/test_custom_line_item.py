"""Tests for CUSTOM LineItemType and metadata on InvoiceLineItem."""
import uuid
from decimal import Decimal

from vbwd.models.enums import LineItemType
from vbwd.models.invoice_line_item import InvoiceLineItem


class TestCustomLineItemType:
    """CUSTOM enum value exists and works."""

    def test_custom_type_exists(self):
        assert hasattr(LineItemType, "CUSTOM")
        assert LineItemType.CUSTOM.value == "CUSTOM"

    def test_all_original_types_still_exist(self):
        assert LineItemType.SUBSCRIPTION.value == "SUBSCRIPTION"
        assert LineItemType.TOKEN_BUNDLE.value == "TOKEN_BUNDLE"
        assert LineItemType.ADD_ON.value == "ADD_ON"

    def test_custom_line_item_creation(self):
        line_item = InvoiceLineItem()
        line_item.invoice_id = uuid.uuid4()
        line_item.item_type = LineItemType.CUSTOM
        line_item.item_id = uuid.uuid4()
        line_item.description = "Booking: Dr. Smith — 2026-03-20 10:00"
        line_item.quantity = 1
        line_item.unit_price = Decimal("50.00")
        line_item.total_price = Decimal("50.00")
        line_item.extra_data = {
            "plugin": "booking",
            "resource_name": "Dr. Smith",
            "start_at": "2026-03-20T10:00:00",
        }

        assert line_item.item_type == LineItemType.CUSTOM
        assert line_item.extra_data["plugin"] == "booking"
        assert line_item.extra_data["resource_name"] == "Dr. Smith"


class TestLineItemMetadata:
    """metadata JSON column on InvoiceLineItem."""

    def test_metadata_defaults_to_empty_dict(self):
        line_item = InvoiceLineItem()
        # Default is dict (via column default), but on unsaved instance it's None
        # until the DB assigns the default
        assert line_item.extra_data is None or line_item.extra_data == {}

    def test_metadata_stores_json(self):
        line_item = InvoiceLineItem()
        line_item.extra_data = {
            "booking_id": "abc-123",
            "resource_type": "specialist",
            "custom_fields": {"symptoms": "headache"},
        }

        assert line_item.extra_data["booking_id"] == "abc-123"
        assert line_item.extra_data["custom_fields"]["symptoms"] == "headache"

    def test_metadata_can_be_none(self):
        line_item = InvoiceLineItem()
        line_item.extra_data = None
        assert line_item.extra_data is None

    def test_to_dict_includes_metadata_when_present(self):
        line_item = InvoiceLineItem()
        line_item.id = uuid.uuid4()
        line_item.invoice_id = uuid.uuid4()
        line_item.item_type = LineItemType.CUSTOM
        line_item.item_id = uuid.uuid4()
        line_item.description = "Test booking"
        line_item.quantity = 1
        line_item.unit_price = Decimal("25.00")
        line_item.total_price = Decimal("25.00")
        line_item.extra_data = {"plugin": "booking", "room": "204"}

        result = line_item.to_dict()

        assert "metadata" in result
        assert result["metadata"]["plugin"] == "booking"
        assert result["metadata"]["room"] == "204"
        assert result["type"] == "CUSTOM"

    def test_to_dict_omits_metadata_when_empty(self):
        line_item = InvoiceLineItem()
        line_item.id = uuid.uuid4()
        line_item.invoice_id = uuid.uuid4()
        line_item.item_type = LineItemType.SUBSCRIPTION
        line_item.item_id = uuid.uuid4()
        line_item.description = "Pro plan"
        line_item.quantity = 1
        line_item.unit_price = Decimal("29.99")
        line_item.total_price = Decimal("29.99")
        line_item.extra_data = None

        result = line_item.to_dict()

        assert "metadata" not in result

    def test_to_dict_omits_metadata_when_empty_dict(self):
        line_item = InvoiceLineItem()
        line_item.id = uuid.uuid4()
        line_item.invoice_id = uuid.uuid4()
        line_item.item_type = LineItemType.SUBSCRIPTION
        line_item.item_id = uuid.uuid4()
        line_item.description = "Pro plan"
        line_item.quantity = 1
        line_item.unit_price = Decimal("29.99")
        line_item.total_price = Decimal("29.99")
        line_item.extra_data = {}

        result = line_item.to_dict()

        assert "metadata" not in result
