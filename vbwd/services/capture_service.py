"""CaptureService — provider-agnostic capture/release for authorized payments."""
import logging

from vbwd.events.bus import event_bus
from vbwd.models.enums import InvoiceStatus
from vbwd.plugins.payment_route_helpers import emit_payment_captured

logger = logging.getLogger(__name__)


class CaptureResult:
    def __init__(self, success: bool, data=None, error=None):
        self.success = success
        self.data = data
        self.error = error


class CaptureService:
    """Captures or releases authorized payments via the provider SDK adapter."""

    def __init__(self, invoice_repository, sdk_registry):
        self._invoice_repo = invoice_repository
        self._sdk_registry = sdk_registry

    def capture(self, invoice_id) -> CaptureResult:
        """Capture an authorized payment.

        Calls the provider's capture_payment(), then emits PaymentCapturedEvent
        which triggers the existing PaymentCapturedHandler to activate items.
        """
        invoice = self._invoice_repo.find_by_id(invoice_id)
        if not invoice:
            return CaptureResult(success=False, error=f"Invoice {invoice_id} not found")

        if invoice.status != InvoiceStatus.AUTHORIZED:
            return CaptureResult(
                success=False,
                error=f"Invoice status is {invoice.status.value}, expected AUTHORIZED",
            )

        if not invoice.payment_intent_id:
            return CaptureResult(success=False, error="No payment_intent_id on invoice")

        adapter = self._sdk_registry.get(invoice.payment_method)
        result = adapter.capture_payment(invoice.payment_intent_id)

        if not result.success:
            return CaptureResult(success=False, error=result.error)

        emit_payment_captured(
            invoice_id=invoice.id,
            payment_reference=invoice.payment_ref,
            amount=str(invoice.amount),
            currency=invoice.currency,
            provider=invoice.payment_method,
            transaction_id=invoice.payment_intent_id,
        )

        logger.info("Invoice %s captured via %s", invoice.id, invoice.payment_method)

        return CaptureResult(
            success=True,
            data={"invoice_id": str(invoice.id), "status": "PAID"},
        )

    def release(self, invoice_id) -> CaptureResult:
        """Release (void) an authorized payment."""
        invoice = self._invoice_repo.find_by_id(invoice_id)
        if not invoice:
            return CaptureResult(success=False, error=f"Invoice {invoice_id} not found")

        if invoice.status != InvoiceStatus.AUTHORIZED:
            return CaptureResult(
                success=False,
                error=f"Invoice status is {invoice.status.value}, expected AUTHORIZED",
            )

        if not invoice.payment_intent_id:
            return CaptureResult(success=False, error="No payment_intent_id on invoice")

        adapter = self._sdk_registry.get(invoice.payment_method)
        result = adapter.release_authorization(invoice.payment_intent_id)

        if not result.success:
            return CaptureResult(success=False, error=result.error)

        invoice.mark_cancelled()
        self._invoice_repo.save(invoice)

        event_bus.publish(
            "invoice.released",
            {
                "invoice_id": str(
                    getattr(invoice, "invoice_number", None) or invoice.id
                ),
                "invoice_uuid": str(invoice.id),
                "user_id": str(invoice.user_id),
                "amount": str(invoice.amount),
            },
        )

        logger.info("Invoice %s authorization released", invoice.id)

        return CaptureResult(
            success=True,
            data={"invoice_id": str(invoice.id), "status": "CANCELLED"},
        )
