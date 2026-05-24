"""Tests for InvoiceService."""
from unittest.mock import MagicMock
from decimal import Decimal
from datetime import datetime, timedelta
from uuid import uuid4

from vbwd.models.enums import InvoiceStatus


class TestInvoiceServiceCreation:
    """Tests for invoice creation."""

    def test_create_invoice_success(self):
        """Create invoice with PENDING status."""
        from vbwd.services.invoice_service import InvoiceService

        mock_repo = MagicMock()
        mock_repo.save.return_value = MagicMock(
            id=uuid4(),
            status=InvoiceStatus.PENDING,
            invoice_number="INV-20251229-ABC123",
        )

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.create_invoice(
            user_id=str(uuid4()),
            amount=Decimal("99.99"),
            currency="USD",
        )

        assert result.success is True
        assert result.invoice is not None
        assert result.invoice.status == InvoiceStatus.PENDING
        mock_repo.save.assert_called_once()

    def test_create_invoice_generates_unique_number(self):
        """Create invoice generates unique invoice number."""
        from vbwd.services.invoice_service import InvoiceService

        mock_repo = MagicMock()
        saved_invoice = None

        def capture_save(invoice):
            nonlocal saved_invoice
            saved_invoice = invoice
            invoice.id = uuid4()
            return invoice

        mock_repo.save.side_effect = capture_save

        service = InvoiceService(invoice_repository=mock_repo)
        service.create_invoice(
            user_id=str(uuid4()),
            amount=Decimal("50.00"),
        )

        assert saved_invoice is not None
        assert saved_invoice.invoice_number.startswith("INV-")

    def test_create_invoice_sets_due_date(self):
        """Create invoice sets default due date (30 days)."""
        from vbwd.services.invoice_service import InvoiceService

        mock_repo = MagicMock()
        saved_invoice = None

        def capture_save(invoice):
            nonlocal saved_invoice
            saved_invoice = invoice
            invoice.id = uuid4()
            return invoice

        mock_repo.save.side_effect = capture_save

        service = InvoiceService(invoice_repository=mock_repo)
        service.create_invoice(
            user_id=str(uuid4()),
            amount=Decimal("50.00"),
            due_days=30,
        )

        assert saved_invoice.expires_at is not None
        # Should be approximately 30 days from now
        expected = datetime.utcnow() + timedelta(days=30)
        diff = abs((saved_invoice.expires_at - expected).total_seconds())
        assert diff < 60  # Within 1 minute


class TestInvoiceServiceRetrieval:
    """Tests for invoice retrieval."""

    def test_get_invoice_by_id(self):
        """Get invoice by ID returns invoice."""
        from vbwd.services.invoice_service import InvoiceService

        invoice_id = uuid4()
        mock_invoice = MagicMock(id=invoice_id)
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = mock_invoice

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.get_invoice(str(invoice_id))

        assert result == mock_invoice
        mock_repo.find_by_id.assert_called_once_with(str(invoice_id))

    def test_get_invoice_not_found(self):
        """Get invoice returns None when not found."""
        from vbwd.services.invoice_service import InvoiceService

        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.get_invoice(str(uuid4()))

        assert result is None

    def test_get_user_invoices(self):
        """Get all invoices for user."""
        from vbwd.services.invoice_service import InvoiceService

        user_id = uuid4()
        mock_invoices = [MagicMock(), MagicMock()]
        mock_repo = MagicMock()
        mock_repo.find_by_user.return_value = mock_invoices

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.get_user_invoices(str(user_id))

        assert result == mock_invoices
        mock_repo.find_by_user.assert_called_once_with(str(user_id))

    def test_get_user_invoices_empty(self):
        """Get user invoices returns empty list when none exist."""
        from vbwd.services.invoice_service import InvoiceService

        mock_repo = MagicMock()
        mock_repo.find_by_user.return_value = []

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.get_user_invoices(str(uuid4()))

        assert result == []

    def test_get_subscription_invoices(self):
        """Get all invoices for subscription."""
        from vbwd.services.invoice_service import InvoiceService

        subscription_id = uuid4()
        mock_invoices = [MagicMock(), MagicMock(), MagicMock()]
        mock_repo = MagicMock()
        mock_repo.find_by_subscription.return_value = mock_invoices

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.get_subscription_invoices(str(subscription_id))

        assert result == mock_invoices
        mock_repo.find_by_subscription.assert_called_once_with(str(subscription_id))


class TestInvoiceServiceStatusTransitions:
    """Tests for invoice status transitions."""

    def test_mark_paid_success(self):
        """Mark invoice as paid (PENDING → PAID)."""
        from vbwd.services.invoice_service import InvoiceService

        invoice_id = uuid4()
        mock_invoice = MagicMock(id=invoice_id, status=InvoiceStatus.PENDING)
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = mock_invoice
        mock_repo.save.return_value = mock_invoice

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.mark_paid(
            invoice_id=str(invoice_id),
            payment_reference="pay_123abc",
            payment_method="stripe",
        )

        assert result.success is True
        mock_invoice.mark_paid.assert_called_once_with("pay_123abc", "stripe")
        mock_repo.save.assert_called_once()

    def test_mark_paid_sets_payment_reference(self):
        """Mark paid stores payment reference."""
        from vbwd.services.invoice_service import InvoiceService

        mock_invoice = MagicMock(status=InvoiceStatus.PENDING)
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = mock_invoice
        mock_repo.save.return_value = mock_invoice

        service = InvoiceService(invoice_repository=mock_repo)
        service.mark_paid(
            invoice_id=str(uuid4()),
            payment_reference="pay_ref_xyz",
            payment_method="paypal",
        )

        mock_invoice.mark_paid.assert_called_with("pay_ref_xyz", "paypal")

    def test_mark_paid_already_paid(self):
        """Mark paid returns error if already paid."""
        from vbwd.services.invoice_service import InvoiceService

        mock_invoice = MagicMock(status=InvoiceStatus.PAID)
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = mock_invoice

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.mark_paid(
            invoice_id=str(uuid4()),
            payment_reference="pay_123",
            payment_method="stripe",
        )

        assert result.success is False
        assert "already paid" in result.error.lower()

    def test_mark_paid_not_found(self):
        """Mark paid returns error if invoice not found."""
        from vbwd.services.invoice_service import InvoiceService

        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = None

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.mark_paid(
            invoice_id=str(uuid4()),
            payment_reference="pay_123",
            payment_method="stripe",
        )

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_mark_failed(self):
        """Mark invoice as failed (PENDING → FAILED)."""
        from vbwd.services.invoice_service import InvoiceService

        mock_invoice = MagicMock(status=InvoiceStatus.PENDING)
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = mock_invoice
        mock_repo.save.return_value = mock_invoice

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.mark_failed(str(uuid4()))

        assert result.success is True
        mock_invoice.mark_failed.assert_called_once()

    def test_mark_cancelled(self):
        """Mark invoice as cancelled (PENDING → CANCELLED)."""
        from vbwd.services.invoice_service import InvoiceService

        mock_invoice = MagicMock(status=InvoiceStatus.PENDING)
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = mock_invoice
        mock_repo.save.return_value = mock_invoice

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.mark_cancelled(str(uuid4()))

        assert result.success is True
        mock_invoice.mark_cancelled.assert_called_once()

    def test_mark_refunded(self):
        """Mark invoice as refunded (PAID → REFUNDED)."""
        from vbwd.services.invoice_service import InvoiceService

        mock_invoice = MagicMock(status=InvoiceStatus.PAID)
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = mock_invoice
        mock_repo.save.return_value = mock_invoice

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.mark_refunded(
            invoice_id=str(uuid4()), refund_reference="refund_123"
        )

        assert result.success is True
        mock_invoice.mark_refunded.assert_called_once()

    def test_mark_refunded_not_paid(self):
        """Mark refunded returns error if not paid."""
        from vbwd.services.invoice_service import InvoiceService

        mock_invoice = MagicMock(status=InvoiceStatus.PENDING)
        mock_repo = MagicMock()
        mock_repo.find_by_id.return_value = mock_invoice

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.mark_refunded(
            invoice_id=str(uuid4()), refund_reference="refund_123"
        )

        assert result.success is False
        assert (
            "not paid" in result.error.lower()
            or "cannot refund" in result.error.lower()
        )


class TestInvoiceServiceQueries:
    """Tests for invoice queries."""

    def test_get_pending_invoices(self):
        """Get all pending invoices."""
        from vbwd.services.invoice_service import InvoiceService

        mock_invoices = [MagicMock(), MagicMock()]
        mock_repo = MagicMock()
        mock_repo.find_pending.return_value = mock_invoices

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.get_pending_invoices()

        assert result == mock_invoices
        mock_repo.find_pending.assert_called_once()

    def test_get_overdue_invoices(self):
        """Get invoices past due date."""
        from vbwd.services.invoice_service import InvoiceService

        mock_invoices = [MagicMock()]
        mock_repo = MagicMock()
        mock_repo.find_overdue.return_value = mock_invoices

        service = InvoiceService(invoice_repository=mock_repo)
        result = service.get_overdue_invoices()

        assert result == mock_invoices
        mock_repo.find_overdue.assert_called_once()
