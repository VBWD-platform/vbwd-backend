"""Unit tests for the live PaymentCapturedHandler (vbwd/handlers/payment_handler.py).

Asserts the handler records the **capturing** provider in invoice.payment_method
(generic; closes s11 item 1) while preserving the existing mark-paid behaviour
for stripe/paypal (regression). The handler now routes through invoice.mark_paid
for the PAID transition (DRY).
"""
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.events.payment_events import PaymentCapturedEvent
from vbwd.handlers.payment_handler import PaymentCapturedHandler


@pytest.fixture(autouse=True)
def _patch_event_bus(monkeypatch):
    """Silence the in-process event bus — out of scope for this handler test."""
    from vbwd.events import bus

    monkeypatch.setattr(bus.event_bus, "publish", lambda *args, **kwargs: None)


def _fake_invoice(initial_status: str = "PENDING", initial_method: str = "stripe"):
    invoice = MagicMock()
    invoice.id = uuid4()
    invoice.user_id = uuid4()
    invoice.invoice_number = "INV-T"
    invoice.amount = Decimal("9.99")
    status = MagicMock()
    status.value = initial_status
    invoice.status = status
    invoice.payment_method = initial_method
    invoice.payment_ref = None
    invoice.paid_at = None
    invoice.line_items = []

    def fake_mark_paid(payment_ref, payment_method):
        new_status = MagicMock()
        new_status.value = "PAID"
        invoice.status = new_status
        invoice.payment_ref = payment_ref
        invoice.payment_method = payment_method

    invoice.mark_paid.side_effect = fake_mark_paid
    return invoice


def _container_for(invoice):
    container = MagicMock()
    container.invoice_repository.return_value.find_by_id.return_value = invoice
    user = MagicMock()
    user.email = "user@example.com"
    container.user_repository.return_value.find_by_id.return_value = user
    return container


def _event(provider: str = "stripe", invoice_id=None) -> PaymentCapturedEvent:
    return PaymentCapturedEvent(
        invoice_id=invoice_id or uuid4(),
        payment_reference="ref-abc",
        amount=Decimal("9.99"),
        currency="USD",
        provider=provider,
        transaction_id="tx-1",
    )


def test_records_capturing_provider_for_token_payment():
    """A token-payment capture sets invoice.payment_method = 'token_payment'."""
    invoice = _fake_invoice(initial_method="invoice")
    container = _container_for(invoice)
    event = _event(provider="token_payment", invoice_id=invoice.id)

    result = PaymentCapturedHandler(container).handle(event)

    assert result.success
    invoice.mark_paid.assert_called_once_with("ref-abc", "token_payment")
    assert invoice.payment_method == "token_payment"


def test_no_regression_for_stripe():
    """A stripe capture leaves payment_method = 'stripe' (provider == code)."""
    invoice = _fake_invoice(initial_method="stripe")
    container = _container_for(invoice)
    event = _event(provider="stripe", invoice_id=invoice.id)

    PaymentCapturedHandler(container).handle(event)

    invoice.mark_paid.assert_called_once_with("ref-abc", "stripe")
    assert invoice.payment_method == "stripe"


def test_no_regression_for_paypal():
    invoice = _fake_invoice(initial_method="paypal")
    container = _container_for(invoice)
    event = _event(provider="paypal", invoice_id=invoice.id)

    PaymentCapturedHandler(container).handle(event)

    assert invoice.payment_method == "paypal"


def test_falls_back_to_existing_method_when_provider_is_absent():
    """No provider on the event → keep the invoice's existing method."""
    invoice = _fake_invoice(initial_method="stripe")
    container = _container_for(invoice)
    event = _event(provider=None, invoice_id=invoice.id)

    PaymentCapturedHandler(container).handle(event)

    invoice.mark_paid.assert_called_once_with("ref-abc", "stripe")
    assert invoice.payment_method == "stripe"


def test_skips_when_already_paid():
    """Idempotent: a re-emitted capture on a PAID invoice mutates nothing."""
    invoice = _fake_invoice(initial_status="PAID", initial_method="stripe")
    container = _container_for(invoice)
    event = _event(provider="token_payment", invoice_id=invoice.id)

    PaymentCapturedHandler(container).handle(event)

    invoice.mark_paid.assert_not_called()
    assert invoice.payment_method == "stripe"
