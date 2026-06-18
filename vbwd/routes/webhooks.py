"""Webhook routes for payment providers."""
from flask import Blueprint, request, jsonify, current_app
from uuid import UUID
from vbwd.events.payment_events import PaymentCapturedEvent
from vbwd.middleware.auth import require_auth, require_permission
from vbwd.services.core_settings_store import get_default_currency

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/api/v1/webhooks")


@webhooks_bp.route("/payment", methods=["POST"])
@require_auth
@require_permission("invoices.manage")
def payment_webhook():
    """
    Manually mark an invoice as paid (admin-only).

    Despite the legacy "webhook" name this core endpoint is NOT a public
    provider webhook — real payment providers post to their own
    signature-validated plugin webhooks (stripe/paypal/yookassa/...). This
    route is only the admin "manually mark invoice as paid" tool, so it is
    gated behind authentication + the ``invoices.manage`` permission (S90
    DoD #7 / G5: it previously took no auth and no signature, letting anyone
    forge a paid event).

    Request body:
        {
            "invoice_id": "uuid-here",
            "payment_reference": "PAY-123",
            "amount": "29.00",
            "currency": "USD"
        }

    Returns:
        200: {
            "status": "success",
            "invoice_id": "uuid",
            "items_activated": {...}
        }
        400: If validation fails or invoice not found
        500: Server error
    """
    data = request.get_json() or {}

    invoice_id = data.get("invoice_id")
    payment_reference = data.get("payment_reference")
    amount = data.get("amount")
    currency = data.get("currency") or get_default_currency()

    # Validate required fields
    if not invoice_id:
        return jsonify({"error": "invoice_id is required"}), 400
    if not payment_reference:
        return jsonify({"error": "payment_reference is required"}), 400
    if not amount:
        return jsonify({"error": "amount is required"}), 400

    # Validate UUID format
    try:
        invoice_uuid = UUID(invoice_id) if isinstance(invoice_id, str) else invoice_id
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid invoice_id format"}), 400

    try:
        # Create payment event
        event = PaymentCapturedEvent(
            invoice_id=invoice_uuid,
            payment_reference=payment_reference,
            amount=str(amount),
            currency=currency,
        )

        # Dispatch event
        container = current_app.container
        dispatcher = container.event_dispatcher()
        result = dispatcher.emit(event)

        if result.success:
            # Unwrap single-item list from EventResult.combine()
            data = result.data
            if isinstance(data, list) and len(data) == 1:
                data = data[0]
            return jsonify({"status": "success", **data}), 200
        else:
            return jsonify({"error": result.error}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@webhooks_bp.route("/payment/test", methods=["POST"])
def payment_test_webhook():
    """
    Test endpoint to verify webhook is reachable.

    Returns:
        200: {"status": "ok", "message": "Webhook endpoint is reachable"}
    """
    return jsonify({"status": "ok", "message": "Webhook endpoint is reachable"}), 200
