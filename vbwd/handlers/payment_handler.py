"""Payment event handlers."""
from typing import Any

from vbwd.events.domain import DomainEvent, EventResult, IEventHandler
from vbwd.events.line_item_registry import LineItemContext, line_item_registry
from vbwd.events.payment_events import PaymentCapturedEvent
from vbwd.utils.datetime_utils import utcnow


class PaymentCapturedHandler(IEventHandler):
    """Handler for payment capture events.

    Marks invoice as paid, then delegates line item processing
    to the LineItemHandlerRegistry. Each plugin handles its own
    line item types (subscriptions, bookings, tokens, etc.).
    """

    def __init__(self, container):
        self._container = container

    def _get_repos(self):
        return {
            "invoice": self._container.invoice_repository(),
            "user": self._container.user_repository(),
        }

    def can_handle(self, event: DomainEvent) -> bool:
        return isinstance(event, PaymentCapturedEvent)

    def handle(self, event: DomainEvent) -> EventResult:
        if not isinstance(event, PaymentCapturedEvent):
            return EventResult.error_result("Invalid event type")

        try:
            repos = self._get_repos()

            # 1. Get and validate invoice
            invoice = repos["invoice"].find_by_id(event.invoice_id)
            if not invoice:
                return EventResult.error_result(f"Invoice {event.invoice_id} not found")

            # 2. Mark invoice as paid — route through invoice.mark_paid (single
            #    home for the PAID transition, DRY) and record the CAPTURING
            #    provider in payment_method, falling back to the invoice's
            #    existing method when the event has no provider set.
            invoice_dirty = False
            if invoice.status.value != "PAID":
                invoice.mark_paid(
                    event.payment_reference,
                    event.provider or invoice.payment_method or "",
                )
                invoice_dirty = True

            # 2b. Merge plugin-contributed metadata into invoice.metadata
            #     (agnostic seam): each plugin owns its top-level namespace
            #     key — core never names the inner shape. Reassign the dict
            #     so SQLAlchemy detects the JSON change. Runs even when the
            #     invoice was already PAID (webhooks may arrive after the
            #     synchronous capture has flipped the status).
            if event.metadata:
                existing = dict(invoice.payment_metadata or {})
                for namespace_key, payload in event.metadata.items():
                    existing[namespace_key] = payload
                invoice.payment_metadata = existing
                invoice_dirty = True

            if invoice_dirty:
                repos["invoice"].save(invoice)

            # 3. Delegate line item processing to registered handlers
            context = LineItemContext(
                invoice=invoice,
                user_id=invoice.user_id,
                container=self._container,
            )
            items_activated: dict[str, Any] = {
                "subscription": None,
                "token_bundles": [],
                "add_ons": [],
                "tokens_credited": 0,
            }

            for line_item in invoice.line_items:
                result = line_item_registry.process_activation(line_item, context)
                if result.success and not result.skipped:
                    self._collect_activation_result(result, items_activated)

            # 4. Publish invoice.paid bus event for email/notifications
            from vbwd.events.bus import event_bus

            user = repos["user"].find_by_id(invoice.user_id)
            user_email = user.email if user else ""
            user_name = user_email

            paid_date = (
                invoice.paid_at.date().isoformat()
                if invoice.paid_at
                else utcnow().date().isoformat()
            )
            event_bus.publish(
                "invoice.paid",
                {
                    "user_name": user_name,
                    "user_email": user_email,
                    "invoice_id": str(
                        getattr(invoice, "invoice_number", None) or invoice.id
                    ),
                    "amount": str(invoice.amount),
                    "paid_date": paid_date,
                    "invoice_url": f"/invoices/{invoice.id}",
                },
            )

            return EventResult.success_result(
                {
                    "invoice_id": str(invoice.id),
                    "status": "paid",
                    "payment_reference": event.payment_reference,
                    "items_activated": items_activated,
                }
            )

        except Exception as exception:
            return EventResult.error_result(str(exception))

    def _collect_activation_result(self, result, items_activated: dict) -> None:
        """Merge a line item handler result into the aggregate dict."""
        data = result.data
        if "subscription_id" in data:
            items_activated["subscription"] = data["subscription_id"]
        if "purchase_id" in data:
            items_activated["token_bundles"].append(data["purchase_id"])
        if "addon_subscription_id" in data:
            items_activated["add_ons"].append(data["addon_subscription_id"])
        items_activated["tokens_credited"] += data.get("tokens_credited", 0)
