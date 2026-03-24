"""Tests for AutoCaptureHandler — captures authorized invoices on events."""
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from vbwd.models.enums import InvoiceStatus


class TestAutoCaptureHandler:
    def _make_handler(self, invoice=None):
        from vbwd.handlers.auto_capture_handler import AutoCaptureHandler

        container = MagicMock()
        invoice_repo = MagicMock()
        if invoice:
            invoice_repo.find_by_id.return_value = invoice
        else:
            invoice_repo.find_by_id.return_value = None
        container.invoice_repository.return_value = invoice_repo

        sdk_registry = MagicMock()
        handler = AutoCaptureHandler(container, sdk_registry=sdk_registry)
        return handler, invoice_repo, container

    def test_captures_authorized_invoice_on_booking_completed(self):
        invoice = MagicMock()
        invoice.id = uuid.uuid4()
        invoice.status = InvoiceStatus.AUTHORIZED
        invoice.payment_method = "stripe"
        invoice.payment_intent_id = "pi_auto_123"
        invoice.payment_ref = "pi_auto_123"
        invoice.amount = Decimal("50.00")
        invoice.currency = "EUR"

        handler, invoice_repo, _ = self._make_handler(invoice)

        with patch("vbwd.handlers.auto_capture_handler.CaptureService") as mock_cls:
            mock_service = MagicMock()
            mock_service.capture.return_value = MagicMock(success=True)
            mock_cls.return_value = mock_service

            handler.on_booking_completed(
                "booking.completed",
                {
                    "booking_id": str(uuid.uuid4()),
                    "user_id": str(uuid.uuid4()),
                    "invoice_id": str(invoice.id),
                },
            )

        mock_service.capture.assert_called_once_with(invoice.id)

    def test_skips_non_authorized_invoice(self):
        invoice = MagicMock()
        invoice.id = uuid.uuid4()
        invoice.status = InvoiceStatus.PAID

        handler, _, _ = self._make_handler(invoice)

        with patch("vbwd.handlers.auto_capture_handler.CaptureService") as mock_cls:
            mock_service = MagicMock()
            mock_cls.return_value = mock_service

            handler.on_booking_completed(
                "booking.completed",
                {
                    "booking_id": str(uuid.uuid4()),
                    "user_id": str(uuid.uuid4()),
                    "invoice_id": str(invoice.id),
                },
            )

        mock_service.capture.assert_not_called()

    def test_skips_when_no_invoice_id(self):
        handler, invoice_repo, _ = self._make_handler()

        with patch("vbwd.handlers.auto_capture_handler.CaptureService"):
            handler.on_booking_completed(
                "booking.completed",
                {"booking_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4())},
            )

        invoice_repo.find_by_id.assert_not_called()

    def test_handles_invoice_not_found(self):
        handler, invoice_repo, _ = self._make_handler(invoice=None)

        with patch("vbwd.handlers.auto_capture_handler.CaptureService"):
            handler.on_booking_completed(
                "booking.completed",
                {
                    "booking_id": str(uuid.uuid4()),
                    "invoice_id": str(uuid.uuid4()),
                },
            )
        # Should not raise
