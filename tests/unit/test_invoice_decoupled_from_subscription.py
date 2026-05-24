"""S4 oracle — core invoice carries no subscription/plan FK.

The subscription↔invoice link lives in the invoice's SUBSCRIPTION line item
(item_id == subscription.id), not in columns on the core invoice table. Core
must therefore expose no ``subscription_id`` / ``tarif_plan_id`` on the invoice
model or its serialisation.
"""
from decimal import Decimal
from uuid import uuid4

from vbwd.models.enums import InvoiceStatus
from vbwd.models.invoice import UserInvoice


def _pending_invoice() -> UserInvoice:
    return UserInvoice(
        id=uuid4(),
        user_id=uuid4(),
        invoice_number=UserInvoice.generate_invoice_number(),
        amount=Decimal("9.99"),
        currency="EUR",
        status=InvoiceStatus.PENDING,
    )


def test_invoice_model_has_no_subscription_or_plan_columns():
    """The core invoice table defines neither FK column."""
    columns = {column.name for column in UserInvoice.__table__.columns}
    assert "subscription_id" not in columns
    assert "tarif_plan_id" not in columns


def test_invoice_to_dict_omits_subscription_and_plan_fields():
    """Serialised core invoice exposes no subscription/plan linkage."""
    payload = _pending_invoice().to_dict()
    assert "subscription_id" not in payload
    assert "tarif_plan_id" not in payload
