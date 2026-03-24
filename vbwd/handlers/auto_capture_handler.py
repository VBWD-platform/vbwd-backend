"""AutoCaptureHandler — captures authorized invoices on configurable events."""
import logging

from vbwd.models.enums import InvoiceStatus
from vbwd.services.capture_service import CaptureService

logger = logging.getLogger(__name__)


class AutoCaptureHandler:
    """Listens for events (e.g., booking.completed) and auto-captures
    AUTHORIZED invoices linked to them.

    Subscribed to EventBus (not DomainEventDispatcher) so plugins can
    trigger captures without modifying core.
    """

    def __init__(self, container, sdk_registry=None):
        self._container = container
        self._sdk_registry = sdk_registry

    def on_booking_completed(self, event_name: str, data: dict) -> None:
        """EventBus callback for booking.completed."""
        invoice_id = data.get("invoice_id")
        if not invoice_id:
            return

        invoice_repo = self._container.invoice_repository()
        invoice = invoice_repo.find_by_id(invoice_id)
        if not invoice:
            logger.debug("AutoCapture: invoice %s not found", invoice_id)
            return

        if invoice.status != InvoiceStatus.AUTHORIZED:
            return

        sdk_registry = self._sdk_registry
        if not sdk_registry:
            from flask import current_app

            sdk_registry = getattr(current_app, "sdk_registry", None)
        if not sdk_registry:
            logger.warning("AutoCapture: no sdk_registry available")
            return

        service = CaptureService(
            invoice_repository=invoice_repo,
            sdk_registry=sdk_registry,
        )
        result = service.capture(invoice.id)

        if result.success:
            logger.info(
                "AutoCapture: invoice %s captured on %s", invoice.id, event_name
            )
        else:
            logger.warning(
                "AutoCapture: failed to capture invoice %s: %s",
                invoice.id,
                result.error,
            )
