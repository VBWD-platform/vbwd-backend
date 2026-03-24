"""Tests for CaptureService — TDD-first."""
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from vbwd.models.enums import InvoiceStatus


class TestCaptureServiceCapture:
    def _make_service(self, invoice=None, adapter_response=None):
        invoice_repo = MagicMock()
        invoice_repo.find_by_id.return_value = invoice
        sdk_registry = MagicMock()
        adapter = MagicMock()
        if adapter_response:
            adapter.capture_payment.return_value = adapter_response
        else:
            adapter.capture_payment.return_value = MagicMock(
                success=True, data={"status": "succeeded"}
            )
        sdk_registry.get.return_value = adapter

        from vbwd.services.capture_service import CaptureService

        service = CaptureService(
            invoice_repository=invoice_repo,
            sdk_registry=sdk_registry,
        )
        return service, invoice_repo, adapter

    def test_capture_succeeds_for_authorized_invoice(self):
        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.status = InvoiceStatus.AUTHORIZED
        invoice.payment_method = "stripe"
        invoice.payment_intent_id = "pi_test_123"
        invoice.payment_ref = "pi_test_123"
        invoice.amount = Decimal("50.00")
        invoice.currency = "EUR"
        invoice.user_id = uuid4()

        service, invoice_repo, adapter = self._make_service(invoice)

        with patch("vbwd.services.capture_service.emit_payment_captured"):
            result = service.capture(invoice.id)

        assert result.success
        adapter.capture_payment.assert_called_once_with("pi_test_123")

    def test_capture_emits_payment_captured_event(self):
        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.status = InvoiceStatus.AUTHORIZED
        invoice.payment_method = "stripe"
        invoice.payment_intent_id = "pi_test_123"
        invoice.payment_ref = "pi_test_123"
        invoice.amount = Decimal("50.00")
        invoice.currency = "EUR"

        service, _, _ = self._make_service(invoice)

        with patch("vbwd.services.capture_service.emit_payment_captured") as mock_emit:
            service.capture(invoice.id)

        mock_emit.assert_called_once()

    def test_capture_fails_for_non_authorized_invoice(self):
        invoice = MagicMock()
        invoice.status = InvoiceStatus.PENDING

        service, _, _ = self._make_service(invoice)

        result = service.capture(invoice.id)

        assert not result.success
        assert "AUTHORIZED" in result.error

    def test_capture_fails_if_invoice_not_found(self):
        service, _, _ = self._make_service(invoice=None)

        result = service.capture(uuid4())

        assert not result.success

    def test_capture_fails_if_provider_capture_fails(self):
        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.status = InvoiceStatus.AUTHORIZED
        invoice.payment_method = "stripe"
        invoice.payment_intent_id = "pi_fail"

        failed_response = MagicMock(success=False, error="Card declined")
        service, _, _ = self._make_service(invoice, adapter_response=failed_response)

        result = service.capture(invoice.id)

        assert not result.success
        assert "Card declined" in result.error


class TestCaptureServiceRelease:
    def _make_service(self, invoice=None):
        invoice_repo = MagicMock()
        invoice_repo.find_by_id.return_value = invoice
        sdk_registry = MagicMock()
        adapter = MagicMock()
        adapter.release_authorization.return_value = MagicMock(
            success=True, data={"status": "canceled"}
        )
        sdk_registry.get.return_value = adapter

        from vbwd.services.capture_service import CaptureService

        service = CaptureService(
            invoice_repository=invoice_repo,
            sdk_registry=sdk_registry,
        )
        return service, invoice_repo, adapter

    def test_release_cancels_authorized_invoice(self):
        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.status = InvoiceStatus.AUTHORIZED
        invoice.payment_method = "stripe"
        invoice.payment_intent_id = "pi_release"

        service, _, adapter = self._make_service(invoice)

        with patch("vbwd.services.capture_service.event_bus"):
            result = service.release(invoice.id)

        assert result.success
        adapter.release_authorization.assert_called_once_with("pi_release")
        invoice.mark_cancelled.assert_called_once()

    def test_release_publishes_invoice_released_event(self):
        invoice = MagicMock()
        invoice.id = uuid4()
        invoice.status = InvoiceStatus.AUTHORIZED
        invoice.payment_method = "stripe"
        invoice.payment_intent_id = "pi_release"
        invoice.user_id = uuid4()
        invoice.invoice_number = "BK-REL"
        invoice.amount = Decimal("50.00")

        service, _, _ = self._make_service(invoice)

        with patch("vbwd.services.capture_service.event_bus") as mock_bus:
            service.release(invoice.id)

        mock_bus.publish.assert_called_once()
        assert mock_bus.publish.call_args[0][0] == "invoice.released"

    def test_release_fails_for_non_authorized_invoice(self):
        invoice = MagicMock()
        invoice.status = InvoiceStatus.PAID

        service, _, _ = self._make_service(invoice)

        with patch("vbwd.services.capture_service.event_bus"):
            result = service.release(invoice.id)

        assert not result.success
