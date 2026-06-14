"""S85.4 gap #1 — the core invoice line item persists + exposes the per-rate
tax breakdown so the invoice tax disclosure can render real VAT lines.

``InvoiceLineItem`` gains three first-class columns: ``net_amount``,
``tax_amount`` (both ``Numeric(10,2)``) and ``tax_breakdown`` (JSONB, default
empty list) holding ``[{"code", "rate", "amount"}]``. ``to_dict()`` exposes
them. ``total_price`` stays the gross. Core stays plugin-agnostic — these are
generic fields the plugins populate.
"""
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.dialects.postgresql import JSONB

from vbwd.models.enums import InvoiceStatus, LineItemType
from vbwd.models.invoice import UserInvoice
from vbwd.models.invoice_line_item import InvoiceLineItem


def _line_item(**overrides) -> InvoiceLineItem:
    defaults = dict(
        id=uuid4(),
        invoice_id=uuid4(),
        item_type=LineItemType.CUSTOM,
        item_id=uuid4(),
        description="Taxed sellable",
        quantity=1,
        unit_price=Decimal("10.00"),
        total_price=Decimal("11.90"),
    )
    defaults.update(overrides)
    return InvoiceLineItem(**defaults)


def test_line_item_has_net_tax_and_breakdown_columns():
    columns = {column.name for column in InvoiceLineItem.__table__.columns}
    assert "net_amount" in columns
    assert "tax_amount" in columns
    assert "tax_breakdown" in columns


def test_tax_breakdown_column_is_jsonb():
    column = InvoiceLineItem.__table__.columns["tax_breakdown"]
    assert isinstance(column.type, JSONB)


def test_to_dict_includes_new_fields():
    line = _line_item(
        net_amount=Decimal("10.00"),
        tax_amount=Decimal("1.90"),
        tax_breakdown=[
            {"code": "VAT", "name": "VAT Germany", "rate": 19.0, "amount": 1.90}
        ],
    )
    payload = line.to_dict()
    assert payload["net_amount"] == "10.00"
    assert payload["tax_amount"] == "1.90"
    assert payload["amount"] == "11.90"  # gross unchanged
    assert payload["tax_breakdown"] == [
        {"code": "VAT", "name": "VAT Germany", "rate": 19.0, "amount": 1.90}
    ]


def test_to_dict_defaults_when_breakdown_absent():
    """A taxless / legacy line serialises net==gross, no tax, empty breakdown."""
    line = _line_item(unit_price=Decimal("5.00"), total_price=Decimal("5.00"))
    payload = line.to_dict()
    assert payload["tax_breakdown"] == []
    assert payload["tax_amount"] == "0.00"
    # When net_amount is not set we fall back to the gross total.
    assert payload["net_amount"] == "5.00"


def test_invoice_to_dict_rolls_up_net_tax_gross():
    invoice = UserInvoice(
        id=uuid4(),
        user_id=uuid4(),
        invoice_number=UserInvoice.generate_invoice_number(),
        amount=Decimal("11.90"),
        subtotal=Decimal("10.00"),
        tax_amount=Decimal("1.90"),
        total_amount=Decimal("11.90"),
        currency="EUR",
        status=InvoiceStatus.PENDING,
    )
    payload = invoice.to_dict()
    assert payload["subtotal"] == "10.00"
    assert payload["tax_amount"] == "1.90"
    assert payload["total_amount"] == "11.90"
