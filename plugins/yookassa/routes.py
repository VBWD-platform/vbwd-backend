"""YooKassa plugin API routes."""
import logging
from decimal import Decimal
from uuid import UUID

from flask import Blueprint, jsonify, request, current_app, g

from src.middleware.auth import require_auth
from src.plugins.payment_route_helpers import (
    check_plugin_enabled,
    validate_invoice_for_payment,
    emit_payment_captured,
    determine_session_mode,
)
from src.sdk.interface import SDKConfig
from src.models.enums import LineItemType, InvoiceStatus
from src.models.invoice_line_item import InvoiceLineItem
from src.models.invoice import UserInvoice
from src.events.payment_events import (
    PaymentFailedEvent,
)

logger = logging.getLogger(__name__)

yookassa_plugin_bp = Blueprint("yookassa_plugin", __name__)


def _get_adapter(config):
    """Instantiate YooKassaSDKAdapter from plugin config."""
    from plugins.yookassa.sdk_adapter import YooKassaSDKAdapter

    prefix = "test_" if config.get("sandbox", True) else "live_"
    return YooKassaSDKAdapter(
        SDKConfig(
            api_key=config.get(f"{prefix}shop_id") or config.get("shop_id", ""),
            api_secret=config.get(f"{prefix}secret_key")
            or config.get("secret_key", ""),
            sandbox=config.get("sandbox", True),
        )
    )


@yookassa_plugin_bp.route("/create-session", methods=["POST"])
@require_auth
def create_session():
    """Create a YooKassa payment for a PENDING invoice."""
    config, err = check_plugin_enabled("yookassa")
    if err:
        return err

    data = request.get_json() or {}
    invoice, err = validate_invoice_for_payment(data.get("invoice_id", ""), g.user_id)
    if err:
        return err

    adapter = _get_adapter(config)
    mode = determine_session_mode(invoice)
    base_meta = {"invoice_id": str(invoice.id), "user_id": str(g.user_id)}

    frontend_base = (
        request.headers.get("Origin")
        or request.headers.get("Referer", "").rstrip("/").rsplit("/pay", 1)[0]
        or request.host_url.rstrip("/")
    )
    success_url = f"{frontend_base}/pay/yookassa/success?session_id={{session_id}}"
    cancel_url = f"{frontend_base}/pay/yookassa/cancel"

    if mode == "subscription":
        # YooKassa recurring: save payment method on initial payment
        meta = {
            **base_meta,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "save_payment_method": True,
        }
    else:
        meta = {
            **base_meta,
            "success_url": success_url,
            "cancel_url": cancel_url,
        }

    response = adapter.create_payment_intent(
        amount=Decimal(str(invoice.total_amount or invoice.amount)),
        currency=invoice.currency or "RUB",
        metadata=meta,
    )

    if response.success:
        # Store YooKassa payment ID on invoice for reliable mapping
        yookassa_id = response.data.get("session_id", "")
        if yookassa_id:
            invoice.provider_session_id = yookassa_id
            current_app.container.invoice_repository().save(invoice)

        # Replace placeholder in success URL
        session_url = response.data.get("session_url", "")
        return (
            jsonify(
                {
                    "session_id": yookassa_id,
                    "session_url": session_url,
                }
            ),
            200,
        )

    return jsonify({"error": response.error}), 500


@yookassa_plugin_bp.route("/webhook", methods=["POST"])
def yookassa_webhook():
    """Handle YooKassa webhook events."""
    config, err = check_plugin_enabled("yookassa")
    if err:
        return err

    payload = request.get_data()
    signature = request.headers.get("X-YooKassa-Signature", "")

    prefix = "test_" if config.get("sandbox", True) else "live_"
    webhook_secret = config.get(f"{prefix}webhook_secret") or config.get(
        "webhook_secret", ""
    )

    try:
        from plugins.yookassa.sdk_adapter import YooKassaSDKAdapter

        event = YooKassaSDKAdapter.verify_webhook_signature_static(
            payload, signature, webhook_secret
        )
    except ValueError:
        return jsonify({"error": "Invalid signature"}), 400

    event_type = event.get("event", "")
    obj = event.get("object", {})

    if event_type == "payment.succeeded":
        _handle_payment_succeeded(obj)
    elif event_type == "payment.canceled":
        _handle_payment_canceled(obj)
    elif event_type == "refund.succeeded":
        _handle_refund_succeeded(obj)

    return jsonify({"received": True}), 200


@yookassa_plugin_bp.route("/session-status/<payment_id>", methods=["GET"])
@require_auth
def session_status(payment_id):
    """Poll YooKassa payment status."""
    config, err = check_plugin_enabled("yookassa")
    if err:
        return err

    adapter = _get_adapter(config)
    response = adapter.get_payment_status(payment_id)
    if not response.success:
        return jsonify({"error": response.error}), 500

    status = response.data.get("status", "")
    # Map YooKassa statuses to our standard format
    if status == "succeeded":
        mapped_status = "paid"
    elif status == "canceled":
        mapped_status = "canceled"
    else:
        mapped_status = status  # pending, waiting_for_capture

    # Reconciliation: if YooKassa says succeeded, ensure our invoice is updated
    if mapped_status == "paid":
        invoice_id = response.data.get("invoice_id", "")
        # Fallback: look up invoice by provider_session_id
        if not invoice_id:
            invoice_repo = current_app.container.invoice_repository()
            invoice = invoice_repo.find_by_provider_session_id(payment_id)
            if invoice:
                invoice_id = str(invoice.id)
        if invoice_id:
            _reconcile_payment(invoice_id, payment_id, response.data)

    return (
        jsonify(
            {
                "status": mapped_status,
                "amount_total": response.data.get("amount_total"),
                "currency": response.data.get("currency"),
            }
        ),
        200,
    )


# ---- Webhook Handlers ----


def _handle_payment_succeeded(obj):
    """YooKassa payment succeeded — auto-captured."""
    metadata = obj.get("metadata", {})
    invoice_id_str = metadata.get("invoice_id")
    if not invoice_id_str:
        return

    container = current_app.container
    invoice_repo = container.invoice_repository()
    invoice = invoice_repo.find_by_id(UUID(invoice_id_str))
    if not invoice or invoice.status.value != "PENDING":
        return

    payment_id = obj.get("id", "")
    amount = obj.get("amount", {}).get("value", "0")
    currency = obj.get("amount", {}).get("currency", "RUB")

    # Save payment method for recurring if it was saved
    payment_method = obj.get("payment_method", {})
    if payment_method.get("saved"):
        _save_payment_method_for_subscription(invoice, payment_method.get("id", ""))

    emit_payment_captured(
        invoice_id=UUID(invoice_id_str),
        payment_reference=payment_id,
        amount=amount,
        currency=currency,
        provider="yookassa",
        transaction_id=payment_id,
    )


def _handle_payment_canceled(obj):
    """YooKassa payment canceled."""
    metadata = obj.get("metadata", {})
    invoice_id_str = metadata.get("invoice_id")
    if not invoice_id_str:
        return

    container = current_app.container
    invoice_repo = container.invoice_repository()

    try:
        invoice = invoice_repo.find_by_id(UUID(invoice_id_str))
    except (ValueError, TypeError):
        return

    if not invoice:
        return

    invoice.status = InvoiceStatus.FAILED
    invoice_repo.save(invoice)

    logger.warning(
        "YooKassa payment canceled for invoice %s, payment %s",
        invoice_id_str,
        obj.get("id", ""),
    )

    sub_repo = container.subscription_repository()
    subscription_id = None
    user_id = None
    for li in invoice.line_items:
        if li.item_type == LineItemType.SUBSCRIPTION:
            sub = sub_repo.find_by_id(li.item_id)
            if sub:
                subscription_id = sub.id
                user_id = sub.user_id
            break

    if subscription_id is not None:
        event = PaymentFailedEvent(
            subscription_id=subscription_id,
            user_id=user_id,
            error_code="payment_canceled",
            error_message="YooKassa payment was canceled",
            provider="yookassa",
        )
        container.event_dispatcher().emit(event)


def _handle_refund_succeeded(obj):
    """YooKassa refund succeeded."""
    payment_id = obj.get("payment_id", "")
    refund_id = obj.get("id", "")
    amount = obj.get("amount", {}).get("value", "0")
    logger.info(
        "YooKassa refund %s succeeded for payment %s, amount %s",
        refund_id,
        payment_id,
        amount,
    )


# ---- Helpers ----


def _save_payment_method_for_subscription(invoice, payment_method_id):
    """Store payment_method_id on Subscription for recurring charges."""
    container = current_app.container
    sub_repo = container.subscription_repository()

    for li in invoice.line_items:
        if li.item_type == LineItemType.SUBSCRIPTION:
            subscription = sub_repo.find_by_id(li.item_id)
            if subscription:
                subscription.provider_subscription_id = payment_method_id
                sub_repo.save(subscription)
                break


def _reconcile_payment(invoice_id_str, payment_id, response_data):
    """Emit PaymentCapturedEvent if YooKassa says paid but our invoice is still PENDING."""
    try:
        invoice_id = UUID(invoice_id_str)
    except (ValueError, TypeError):
        return

    container = current_app.container
    invoice_repo = container.invoice_repository()
    invoice = invoice_repo.find_by_id(invoice_id)
    if not invoice or invoice.status != InvoiceStatus.PENDING:
        return

    logger.info(
        "Reconciliation: YooKassa payment %s paid but invoice %s still PENDING",
        payment_id,
        invoice_id,
    )
    emit_payment_captured(
        invoice_id=invoice_id,
        payment_reference=payment_id,
        amount=response_data.get("amount_total", "0"),
        currency=response_data.get("currency", "RUB"),
        provider="yookassa",
        transaction_id=payment_id,
    )
