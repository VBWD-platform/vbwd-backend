"""Handler for payment.authorized — sets invoice to AUTHORIZED status."""
import logging

from vbwd.events.bus import event_bus
from vbwd.events.domain import DomainEvent, EventResult, IEventHandler
from vbwd.events.payment_events import PaymentAuthorizedEvent

logger = logging.getLogger(__name__)


class PaymentAuthorizedHandler(IEventHandler):
    """Sets invoice to AUTHORIZED when payment is authorized (not captured).

    Does NOT activate line items — activation only happens on capture
    (PaymentCapturedHandler).
    """

    def __init__(self, container):
        self._container = container

    def can_handle(self, event: DomainEvent) -> bool:
        return isinstance(event, PaymentAuthorizedEvent)

    def handle(self, event: DomainEvent) -> EventResult:
        if not isinstance(event, PaymentAuthorizedEvent):
            return EventResult.error_result("Invalid event type")

        invoice_repo = self._container.invoice_repository()
        invoice = invoice_repo.find_by_id(event.invoice_id)

        if not invoice:
            return EventResult.error_result(f"Invoice {event.invoice_id} not found")

        invoice.mark_authorized(
            payment_ref=event.payment_reference or "",
            payment_method=event.provider or "",
        )
        invoice.payment_intent_id = event.payment_intent_id
        invoice_repo.save(invoice)

        event_bus.publish(
            "invoice.authorized",
            {
                "invoice_id": str(
                    getattr(invoice, "invoice_number", None) or invoice.id
                ),
                "invoice_uuid": str(invoice.id),
                "user_id": str(invoice.user_id),
                "amount": str(invoice.amount),
                "payment_intent_id": event.payment_intent_id or "",
            },
        )

        logger.info(
            "Invoice %s authorized (payment_intent=%s)",
            invoice.id,
            event.payment_intent_id,
        )

        return EventResult.success_result(
            {
                "invoice_id": str(invoice.id),
                "status": "AUTHORIZED",
                "payment_intent_id": event.payment_intent_id,
            }
        )
