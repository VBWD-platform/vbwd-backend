"""Admin invoice management routes."""
import logging
from datetime import timedelta
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request
from vbwd.middleware.auth import require_auth, require_admin
from vbwd.repositories.invoice_repository import InvoiceRepository
from vbwd.repositories.user_repository import UserRepository
from vbwd.services.invoice_service import InvoiceService
from vbwd.events.payment_events import PaymentCapturedEvent, PaymentRefundedEvent
from vbwd.utils.datetime_utils import utcnow
from vbwd.extensions import db

logger = logging.getLogger(__name__)

admin_invoices_bp = Blueprint(
    "admin_invoices", __name__, url_prefix="/api/v1/admin/invoices"
)


@admin_invoices_bp.route("/", methods=["GET"])
@require_auth
@require_admin
def list_invoices():
    """
    List all invoices with pagination and filters.

    Query params:
        - limit: int (default 20, max 100)
        - offset: int (default 0)
        - status: str (pending, paid, failed, cancelled, refunded)
        - user_id: str (filter by user)

    Returns:
        200: List of invoices with pagination info
    """
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))
    status = request.args.get("status")
    user_id = request.args.get("user_id")

    invoice_repo = InvoiceRepository(db.session)
    user_repo = UserRepository(db.session)

    invoices, total = invoice_repo.find_all_paginated(
        limit=limit, offset=offset, status=status, user_id=user_id
    )

    # Enrich invoices with user info for admin display
    result = []
    for inv in invoices:
        inv_dict = inv.to_dict()
        # Add user email
        user = user_repo.find_by_id(str(inv.user_id))
        inv_dict["user_email"] = user.email if user else ""
        # Add created_at for sorting
        inv_dict["created_at"] = inv.created_at.isoformat() if inv.created_at else None
        result.append(inv_dict)

    return (
        jsonify({"invoices": result, "total": total, "limit": limit, "offset": offset}),
        200,
    )


@admin_invoices_bp.route("/<invoice_id>", methods=["GET"])
@require_auth
@require_admin
def get_invoice(invoice_id):
    """
    Get invoice detail with enriched user, plan, and subscription data.

    Args:
        invoice_id: UUID of the invoice

    Returns:
        200: Invoice details with user, plan, subscription info
        404: Invoice not found
    """
    from vbwd.repositories.tarif_plan_repository import TarifPlanRepository
    from vbwd.repositories.subscription_repository import SubscriptionRepository

    invoice_repo = InvoiceRepository(db.session)
    user_repo = UserRepository(db.session)
    plan_repo = TarifPlanRepository(db.session)
    subscription_repo = SubscriptionRepository(db.session)

    invoice = invoice_repo.find_by_id(invoice_id)

    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404

    inv_dict = invoice.to_dict()

    # Enrich with user info
    user = user_repo.find_by_id(str(invoice.user_id))
    if user:
        inv_dict["user_email"] = user.email
        inv_dict["user_name"] = (
            user.details.first_name + " " + user.details.last_name
            if user.details
            else ""
        )

    # Enrich with tariff plan info
    if invoice.tarif_plan_id:
        plan = plan_repo.find_by_id(str(invoice.tarif_plan_id))
        if plan:
            inv_dict["plan_name"] = plan.name
            inv_dict["plan_description"] = plan.description
            inv_dict["plan_billing_period"] = (
                plan.billing_period.value if plan.billing_period else None
            )
            inv_dict["plan_price"] = str(plan.price) if plan.price else None

    # Enrich with subscription info
    if invoice.subscription_id:
        subscription = subscription_repo.find_by_id(str(invoice.subscription_id))
        if subscription:
            inv_dict["subscription_status"] = (
                subscription.status.value if subscription.status else None
            )
            inv_dict["subscription_start_date"] = (
                subscription.started_at.isoformat() if subscription.started_at else None
            )
            inv_dict["subscription_end_date"] = (
                subscription.expires_at.isoformat() if subscription.expires_at else None
            )
            inv_dict["subscription_is_trial"] = subscription.trial_end_at is not None
            inv_dict["subscription_trial_end"] = (
                subscription.trial_end_at.isoformat()
                if subscription.trial_end_at
                else None
            )

    # Add due_date and created_at
    inv_dict["due_date"] = (
        invoice.expires_at.isoformat()
        if invoice.expires_at
        else invoice.invoiced_at.isoformat()
        if invoice.invoiced_at
        else None
    )
    inv_dict["created_at"] = (
        invoice.created_at.isoformat() if invoice.created_at else None
    )

    return jsonify({"invoice": inv_dict}), 200


@admin_invoices_bp.route("/<invoice_id>/duplicate", methods=["POST"])
@require_auth
@require_admin
def duplicate_invoice(invoice_id):
    """
    Create a new invoice based on an existing one.

    Creates a new invoice for the same user, plan, and subscription
    but with a new invoice number and current date.

    Args:
        invoice_id: UUID of the source invoice

    Returns:
        201: New invoice created
        404: Source invoice not found
    """
    from vbwd.models.invoice import UserInvoice

    invoice_repo = InvoiceRepository(db.session)
    source_invoice = invoice_repo.find_by_id(invoice_id)

    if not source_invoice:
        return jsonify({"error": "Invoice not found"}), 404

    # Create new invoice with same data but new number and date
    new_invoice = UserInvoice(
        user_id=source_invoice.user_id,
        tarif_plan_id=source_invoice.tarif_plan_id,
        subscription_id=source_invoice.subscription_id,
        invoice_number=UserInvoice.generate_invoice_number(),
        amount=source_invoice.amount,
        currency=source_invoice.currency,
        invoiced_at=utcnow(),
        expires_at=utcnow() + timedelta(days=30),
    )

    db.session.add(new_invoice)
    db.session.commit()

    return (
        jsonify(
            {
                "invoice": new_invoice.to_dict(),
                "message": "Invoice duplicated successfully",
            }
        ),
        201,
    )


@admin_invoices_bp.route("/<invoice_id>/mark-paid", methods=["POST"])
@require_auth
@require_admin
def mark_paid(invoice_id):
    """
    Mark invoice as paid manually.

    Args:
        invoice_id: UUID of the invoice

    Body:
        - payment_reference: str (required)
        - payment_method: str (default: 'manual')

    Returns:
        200: Invoice marked as paid
        404: Invoice not found
        400: Invalid operation
    """
    data = request.get_json() or {}
    payment_reference = data.get("payment_reference", "MANUAL")
    payment_method = data.get("payment_method", "manual")

    invoice_repo = InvoiceRepository(db.session)
    invoice_service = InvoiceService(invoice_repository=invoice_repo)

    result = invoice_service.mark_paid(invoice_id, payment_reference, payment_method)

    if not result.success:
        if "not found" in result.error.lower():
            return jsonify({"error": result.error}), 404
        return jsonify({"error": result.error}), 400

    # Dispatch PaymentCapturedEvent to activate subscription, credit tokens, etc.
    event = PaymentCapturedEvent(
        invoice_id=UUID(str(result.invoice.id)),
        payment_reference=payment_reference,
        amount=str(result.invoice.amount),
        currency=result.invoice.currency or "USD",
    )
    dispatcher = current_app.container.event_dispatcher()
    dispatcher.emit(event)

    db.session.commit()

    return (
        jsonify(
            {"invoice": result.invoice.to_dict(), "message": "Invoice marked as paid"}
        ),
        200,
    )


@admin_invoices_bp.route("/<invoice_id>/void", methods=["POST"])
@require_auth
@require_admin
def void_invoice(invoice_id):
    """
    Void/cancel an invoice.

    Args:
        invoice_id: UUID of the invoice

    Returns:
        200: Invoice voided
        404: Invoice not found
    """
    invoice_repo = InvoiceRepository(db.session)
    invoice_service = InvoiceService(invoice_repository=invoice_repo)

    result = invoice_service.mark_cancelled(invoice_id)

    if not result.success:
        if "not found" in result.error.lower():
            return jsonify({"error": result.error}), 404
        return jsonify({"error": result.error}), 400

    return (
        jsonify({"invoice": result.invoice.to_dict(), "message": "Invoice voided"}),
        200,
    )


@admin_invoices_bp.route("/<invoice_id>/refund", methods=["POST"])
@require_auth
@require_admin
def refund_invoice(invoice_id):
    """
    Refund a paid invoice.

    First calls the payment provider API (Stripe/PayPal) to process the actual
    refund, then emits PaymentRefundedEvent to update local state.

    Args:
        invoice_id: UUID of the invoice

    Body:
        - refund_reference: str (optional)

    Returns:
        200: Invoice refunded
        404: Invoice not found
        400: Invoice cannot be refunded
    """
    req_data = request.get_json() or {}
    refund_reference = req_data.get("refund_reference", "ADMIN_REFUND")

    # Load invoice to determine payment provider
    container = current_app.container
    invoice_repo = container.invoice_repository()
    invoice = invoice_repo.find_by_id(UUID(invoice_id))
    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404

    # Pre-check: ensure user has enough tokens before calling payment provider
    refund_service = container.refund_service()
    tokens_needed = refund_service._calculate_tokens_to_debit(invoice)
    if tokens_needed > 0:
        token_service = container.token_service()
        current_balance = token_service.get_balance(invoice.user_id)
        if current_balance < tokens_needed:
            return (
                jsonify(
                    {
                        "error": (
                            f"Insufficient token balance for refund. "
                            f"User has {current_balance} tokens but {tokens_needed} "
                            f"need to be deducted. User must purchase more tokens first."
                        )
                    }
                ),
                400,
            )

    # Call the payment provider API to process the actual refund
    provider_error = _refund_via_provider(invoice)
    if provider_error:
        return jsonify({"error": provider_error}), 400

    event = PaymentRefundedEvent(
        invoice_id=UUID(invoice_id),
        refund_reference=refund_reference,
    )
    dispatcher = container.event_dispatcher()
    result = dispatcher.emit(event)

    if result.success:
        resp_data = result.data
        if isinstance(resp_data, list) and len(resp_data) == 1:
            resp_data = resp_data[0]
        return (
            jsonify(
                {
                    "invoice": resp_data.get("invoice", {})
                    if isinstance(resp_data, dict)
                    else {},
                    "message": "Invoice refunded",
                }
            ),
            200,
        )
    else:
        if result.error and "not found" in result.error.lower():
            return jsonify({"error": result.error}), 404
        return jsonify({"error": result.error}), 400


def _refund_via_provider(invoice):
    """Call payment provider API to issue a real refund. Returns error string or None.

    Uses the plugin system to find the payment provider plugin and call its
    refund_payment() method. The core code never imports provider-specific modules.
    """
    payment_method = invoice.payment_method
    if not payment_method or payment_method == "basic":
        return None  # No external provider to refund

    # Find the payment plugin via plugin_manager
    plugin_manager = getattr(current_app, "plugin_manager", None)
    if not plugin_manager:
        logger.warning("Plugin manager not available, skipping provider refund")
        return None

    plugin = plugin_manager.get_plugin(payment_method)
    if not plugin:
        logger.warning(
            "Payment plugin '%s' not found, skipping provider refund", payment_method
        )
        return None

    if not plugin_manager.is_enabled(payment_method):
        logger.warning(
            "Payment plugin '%s' is disabled, skipping provider refund", payment_method
        )
        return None

    # Use provider_session_id or payment_ref as the transaction reference
    transaction_ref = invoice.provider_session_id or invoice.payment_ref
    if not transaction_ref:
        logger.warning("No provider reference for invoice %s", invoice.id)
        return None

    try:
        result = plugin.refund_payment(transaction_ref)
        if not result.success:
            logger.error(
                "Provider refund failed for invoice %s via %s: %s",
                invoice.id,
                payment_method,
                result.error_message,
            )
            return f"Provider refund failed: {result.error_message}"
        logger.info(
            "Provider refund succeeded for invoice %s via %s",
            invoice.id,
            payment_method,
        )
        return None
    except Exception as e:
        logger.error("Provider refund error for invoice %s: %s", invoice.id, e)
        return f"Provider refund error: {e}"


@admin_invoices_bp.route("/<invoice_id>", methods=["DELETE"])
@require_auth
@require_admin
def delete_invoice(invoice_id):
    """
    Delete an invoice completely.

    Args:
        invoice_id: UUID of the invoice

    Returns:
        200: Invoice deleted successfully
        404: Invoice not found
    """
    invoice_repo = InvoiceRepository(db.session)
    invoice = invoice_repo.find_by_id(invoice_id)

    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404

    # Delete invoice
    invoice_repo.delete(invoice_id)

    return jsonify({"message": "Invoice deleted successfully"}), 200


@admin_invoices_bp.route("/<invoice_id>/pdf", methods=["GET"])
@require_auth
@require_admin
def download_pdf(invoice_id):
    """
    Download invoice PDF.

    Args:
        invoice_id: UUID of the invoice

    Returns:
        200: PDF file
        404: Invoice not found
    """
    invoice_repo = InvoiceRepository(db.session)
    invoice = invoice_repo.find_by_id(invoice_id)

    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404

    # For now, return invoice data as JSON (PDF generation would be a separate service)
    return (
        jsonify(
            {"invoice": invoice.to_dict(), "message": "PDF generation not implemented"}
        ),
        200,
    )


@admin_invoices_bp.route("/<invoice_id>/capture", methods=["POST"])
@require_auth
@require_admin
def capture_authorized_payment(invoice_id):
    """Capture an authorized payment (charge the held funds)."""
    from vbwd.services.capture_service import CaptureService
    from vbwd.sdk.registry import SDKAdapterRegistry

    invoice_repo = InvoiceRepository(db.session)
    sdk_registry = getattr(current_app, "sdk_registry", None)
    if not sdk_registry:
        sdk_registry = SDKAdapterRegistry()

    service = CaptureService(
        invoice_repository=invoice_repo,
        sdk_registry=sdk_registry,
    )

    result = service.capture(invoice_id)
    if not result.success:
        return jsonify({"error": result.error}), 400

    db.session.commit()
    return jsonify(result.data)


@admin_invoices_bp.route("/<invoice_id>/release", methods=["POST"])
@require_auth
@require_admin
def release_authorized_payment(invoice_id):
    """Release (void) an authorized payment."""
    from vbwd.services.capture_service import CaptureService
    from vbwd.sdk.registry import SDKAdapterRegistry

    invoice_repo = InvoiceRepository(db.session)
    sdk_registry = getattr(current_app, "sdk_registry", None)
    if not sdk_registry:
        sdk_registry = SDKAdapterRegistry()

    service = CaptureService(
        invoice_repository=invoice_repo,
        sdk_registry=sdk_registry,
    )

    result = service.release(invoice_id)
    if not result.success:
        return jsonify({"error": result.error}), 400

    db.session.commit()
    return jsonify(result.data)
