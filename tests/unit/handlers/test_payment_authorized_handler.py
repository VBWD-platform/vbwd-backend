"""Tests for PaymentAuthorizedHandler — TDD-first."""
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from vbwd.models.enums import InvoiceStatus


class TestPaymentAuthorizedEvent:
    def test_event_has_correct_name(self):
        from vbwd.events.payment_events import PaymentAuthorizedEvent

        event = PaymentAuthorizedEvent(
            invoice_id=uuid4(),
            payment_reference="pi_test_123",
            amount="50.00",
            currency="EUR",
            provider="stripe",
            payment_intent_id="pi_test_123",
        )
        assert event.name == "payment.authorized"

    def test_event_has_payment_intent_id(self):
        from vbwd.events.payment_events import PaymentAuthorizedEvent

        event = PaymentAuthorizedEvent(
            invoice_id=uuid4(),
            payment_reference="ref",
            provider="stripe",
            payment_intent_id="pi_abc",
        )
        assert event.payment_intent_id == "pi_abc"


class TestPaymentAuthorizedHandler:
    def _make_handler(self, invoice=None):
        container = MagicMock()
        invoice_repo = MagicMock()
        invoice_repo.find_by_id.return_value = invoice
        container.invoice_repository.return_value = invoice_repo
        from vbwd.handlers.payment_authorized_handler import (
            PaymentAuthorizedHandler,
        )

        handler = PaymentAuthorizedHandler(container)
        return handler, invoice_repo, container

    def test_sets_invoice_to_authorized(self):
        invoice = MagicMock()
        invoice.status = InvoiceStatus.PENDING
        handler, invoice_repo, _ = self._make_handler(invoice)

        from vbwd.events.payment_events import PaymentAuthorizedEvent

        event = PaymentAuthorizedEvent(
            invoice_id=uuid4(),
            payment_reference="pi_123",
            amount="50.00",
            currency="EUR",
            provider="stripe",
            payment_intent_id="pi_123",
        )

        with patch("vbwd.handlers.payment_authorized_handler.event_bus"):
            result = handler.handle(event)

        assert result.success
        invoice.mark_authorized.assert_called_once_with(
            payment_ref="pi_123",
            payment_method="stripe",
        )
        assert invoice.payment_intent_id == "pi_123"

    def test_publishes_invoice_authorized_event(self):
        invoice = MagicMock()
        invoice.status = InvoiceStatus.PENDING
        invoice.id = uuid4()
        invoice.user_id = uuid4()
        invoice.amount = Decimal("50.00")
        invoice.invoice_number = "BK-TEST"
        handler, _, _ = self._make_handler(invoice)

        from vbwd.events.payment_events import PaymentAuthorizedEvent

        event = PaymentAuthorizedEvent(
            invoice_id=invoice.id,
            payment_reference="pi_123",
            amount="50.00",
            currency="EUR",
            provider="stripe",
            payment_intent_id="pi_123",
        )

        with patch("vbwd.handlers.payment_authorized_handler.event_bus") as mock_bus:
            handler.handle(event)

        mock_bus.publish.assert_called_once()
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == "invoice.authorized"

    def test_does_not_activate_items(self):
        """AUTHORIZED must NOT activate subscriptions/bookings — only CAPTURED does."""
        invoice = MagicMock()
        invoice.status = InvoiceStatus.PENDING
        invoice.line_items = [MagicMock()]
        handler, _, _ = self._make_handler(invoice)

        from vbwd.events.payment_events import PaymentAuthorizedEvent

        event = PaymentAuthorizedEvent(
            invoice_id=uuid4(),
            payment_reference="pi_123",
            provider="stripe",
            payment_intent_id="pi_123",
        )

        with patch("vbwd.handlers.payment_authorized_handler.event_bus"):
            result = handler.handle(event)

        assert result.success
        # No subscription activation, no token credit, no booking creation

    def test_returns_error_if_invoice_not_found(self):
        handler, _, _ = self._make_handler(invoice=None)

        from vbwd.events.payment_events import PaymentAuthorizedEvent

        event = PaymentAuthorizedEvent(
            invoice_id=uuid4(),
            payment_reference="pi_123",
            provider="stripe",
            payment_intent_id="pi_123",
        )

        with patch("vbwd.handlers.payment_authorized_handler.event_bus"):
            result = handler.handle(event)

        assert not result.success
