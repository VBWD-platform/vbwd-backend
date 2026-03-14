"""Invoice service for managing user invoices."""
from decimal import Decimal
from datetime import timedelta
from src.utils.datetime_utils import utcnow
from typing import Optional, List
from uuid import UUID

from src.repositories.invoice_repository import InvoiceRepository
from src.models.invoice import UserInvoice
from src.models.enums import InvoiceStatus


class InvoiceResult:
    """Result of an invoice operation."""

    def __init__(
        self,
        success: bool,
        invoice: Optional[UserInvoice] = None,
        error: Optional[str] = None,
    ):
        """
        Initialize invoice result.

        Args:
            success: Whether the operation succeeded.
            invoice: The invoice if successful.
            error: Error message if failed.
        """
        self.success = success
        self.invoice = invoice
        self.error = error


class InvoiceService:
    """Service for managing invoices."""

    def __init__(self, invoice_repository: InvoiceRepository):
        """
        Initialize invoice service.

        Args:
            invoice_repository: Repository for invoice operations.
        """
        self._repo = invoice_repository

    def create_invoice(
        self,
        user_id: str,
        subscription_id: str,
        tarif_plan_id: str,
        amount: Decimal,
        currency: str = "EUR",
        due_days: int = 30,
    ) -> InvoiceResult:
        """
        Create a new invoice.

        Args:
            user_id: ID of the user.
            subscription_id: ID of the subscription.
            tarif_plan_id: ID of the tariff plan.
            amount: Invoice amount.
            currency: Currency code (default EUR).
            due_days: Days until invoice expires (default 30).

        Returns:
            InvoiceResult with the created invoice or error.
        """
        try:
            invoice = UserInvoice(
                user_id=UUID(user_id) if isinstance(user_id, str) else user_id,
                subscription_id=UUID(subscription_id)
                if isinstance(subscription_id, str)
                else subscription_id,
                tarif_plan_id=UUID(tarif_plan_id)
                if isinstance(tarif_plan_id, str)
                else tarif_plan_id,
                invoice_number=UserInvoice.generate_invoice_number(),
                amount=amount,
                currency=currency,
                status=InvoiceStatus.PENDING,
                invoiced_at=utcnow(),
                expires_at=utcnow() + timedelta(days=due_days),
            )

            saved_invoice = self._repo.save(invoice)
            return InvoiceResult(success=True, invoice=saved_invoice)

        except Exception as e:
            return InvoiceResult(success=False, error=str(e))

    def get_invoice(self, invoice_id: str) -> Optional[UserInvoice]:
        """
        Get invoice by ID.

        Args:
            invoice_id: ID of the invoice.

        Returns:
            The invoice or None if not found.
        """
        return self._repo.find_by_id(invoice_id)

    def get_user_invoices(self, user_id: str) -> List[UserInvoice]:
        """
        Get all invoices for a user.

        Args:
            user_id: ID of the user.

        Returns:
            List of user's invoices.
        """
        return self._repo.find_by_user(user_id)

    def get_subscription_invoices(self, subscription_id: str) -> List[UserInvoice]:
        """
        Get all invoices for a subscription.

        Args:
            subscription_id: ID of the subscription.

        Returns:
            List of subscription's invoices.
        """
        return self._repo.find_by_subscription(subscription_id)

    def mark_paid(
        self, invoice_id: str, payment_reference: str, payment_method: str
    ) -> InvoiceResult:
        """
        Mark invoice as paid.

        Args:
            invoice_id: ID of the invoice.
            payment_reference: External payment reference.
            payment_method: Payment provider used.

        Returns:
            InvoiceResult with updated invoice or error.
        """
        invoice = self._repo.find_by_id(invoice_id)

        if not invoice:
            return InvoiceResult(success=False, error="Invoice not found")

        if invoice.status == InvoiceStatus.PAID:
            return InvoiceResult(success=False, error="Invoice already paid")

        if invoice.status != InvoiceStatus.PENDING:
            return InvoiceResult(
                success=False,
                error=f"Cannot mark as paid: invoice status is {invoice.status.value}",
            )

        invoice.mark_paid(payment_reference, payment_method)
        saved_invoice = self._repo.save(invoice)
        return InvoiceResult(success=True, invoice=saved_invoice)

    def mark_failed(self, invoice_id: str) -> InvoiceResult:
        """
        Mark invoice as failed.

        Args:
            invoice_id: ID of the invoice.

        Returns:
            InvoiceResult with updated invoice or error.
        """
        invoice = self._repo.find_by_id(invoice_id)

        if not invoice:
            return InvoiceResult(success=False, error="Invoice not found")

        invoice.mark_failed()
        saved_invoice = self._repo.save(invoice)
        return InvoiceResult(success=True, invoice=saved_invoice)

    def mark_cancelled(self, invoice_id: str) -> InvoiceResult:
        """
        Cancel an invoice.

        Args:
            invoice_id: ID of the invoice.

        Returns:
            InvoiceResult with updated invoice or error.
        """
        invoice = self._repo.find_by_id(invoice_id)

        if not invoice:
            return InvoiceResult(success=False, error="Invoice not found")

        invoice.mark_cancelled()
        saved_invoice = self._repo.save(invoice)
        return InvoiceResult(success=True, invoice=saved_invoice)

    def mark_refunded(self, invoice_id: str, refund_reference: str) -> InvoiceResult:
        """
        Mark invoice as refunded.

        Args:
            invoice_id: ID of the invoice.
            refund_reference: External refund reference.

        Returns:
            InvoiceResult with updated invoice or error.
        """
        invoice = self._repo.find_by_id(invoice_id)

        if not invoice:
            return InvoiceResult(success=False, error="Invoice not found")

        if invoice.status != InvoiceStatus.PAID:
            return InvoiceResult(
                success=False, error="Cannot refund: invoice is not paid"
            )

        invoice.mark_refunded()
        saved_invoice = self._repo.save(invoice)
        return InvoiceResult(success=True, invoice=saved_invoice)

    def get_pending_invoices(self) -> List[UserInvoice]:
        """
        Get all pending invoices.

        Returns:
            List of pending invoices.
        """
        return self._repo.find_pending()

    def get_overdue_invoices(self) -> List[UserInvoice]:
        """
        Get invoices past due date.

        Returns:
            List of overdue invoices.
        """
        return self._repo.find_overdue()
