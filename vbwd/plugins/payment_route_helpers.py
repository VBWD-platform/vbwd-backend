"""Shared payment route helpers for all payment provider plugins.

Three helper functions that every payment plugin route calls.
Eliminates the need for each provider to duplicate config_store checks,
invoice validation, and event emission.
"""
import logging
from uuid import UUID
from flask import current_app, jsonify

from vbwd.events.payment_events import PaymentCapturedEvent, PaymentAuthorizedEvent
from vbwd.events.bus import event_bus

logger = logging.getLogger(__name__)


# Domain-neutral recurring-billing facts published by payment webhooks.
# A payment install with no plan concept has no subscriber for these — the
# webhook still succeeds (publish is a no-op when no subscriber is registered),
# so payment plugins stay subscription-free. Any plugin that owns recurring
# objects (e.g. subscription) subscribes and does the work inline (the bus
# dispatches synchronously, in the same request/transaction).
EVENT_PROVIDER_LINKED = "payment.provider_linked"
EVENT_RECURRING_CHARGE = "payment.recurring_charge"
EVENT_PROVIDER_CANCELLED = "payment.provider_cancelled"
EVENT_RECURRING_FAILED = "payment.recurring_failed"
EVENT_INVOICE_FAILED = "payment.invoice_failed"


def publish_provider_linked(invoice_id, provider, provider_ref_id):
    """Publish that a provider's recurring object id is linked to an invoice.

    Subscriber records ``provider_ref_id`` on the recurring object referenced
    by the invoice's line item. No-op if nothing subscribes.
    """
    event_bus.publish(
        EVENT_PROVIDER_LINKED,
        {
            "invoice_id": str(invoice_id),
            "provider": provider,
            "provider_ref_id": provider_ref_id,
        },
    )


def publish_recurring_charge(
    provider,
    provider_ref_id,
    amount,
    currency,
    provider_reference,
    transaction_id="",
    metadata=None,
):
    """Publish a successful recurring charge fact.

    The subscriber finds the matching recurring object, creates the renewal
    invoice, and itself emits ``payment.captured`` (forwarding ``metadata``
    verbatim) so all downstream capture handling is preserved byte-for-byte.
    No-op if nothing subscribes.
    """
    event_bus.publish(
        EVENT_RECURRING_CHARGE,
        {
            "provider": provider,
            "provider_ref_id": provider_ref_id,
            "amount": amount,
            "currency": currency,
            "provider_reference": provider_reference,
            "transaction_id": transaction_id,
            "metadata": metadata or {},
        },
    )


def publish_provider_cancelled(provider, provider_ref_id, reason=None):
    """Publish that the provider cancelled a recurring object. No-op if no sub."""
    event_bus.publish(
        EVENT_PROVIDER_CANCELLED,
        {
            "provider": provider,
            "provider_ref_id": provider_ref_id,
            "reason": reason,
        },
    )


def publish_recurring_failed(provider, provider_ref_id, error_message):
    """Publish a failed recurring charge fact. No-op if nothing subscribes."""
    event_bus.publish(
        EVENT_RECURRING_FAILED,
        {
            "provider": provider,
            "provider_ref_id": provider_ref_id,
            "error_message": error_message,
        },
    )


def publish_invoice_failed(
    invoice_id, provider, error_message, error_code="payment_failed"
):
    """Publish a payment failure keyed by invoice (provider has no ref id).

    No-op if nothing subscribes.
    """
    event_bus.publish(
        EVENT_INVOICE_FAILED,
        {
            "invoice_id": str(invoice_id),
            "provider": provider,
            "error_message": error_message,
            "error_code": error_code,
        },
    )


def check_plugin_enabled(plugin_name: str):
    """Check plugin is enabled via config_store and return its config.

    Every payment route calls this first. Reads from shared JSON config_store
    (multi-worker safe -- no in-memory state).

    Returns:
        (config_dict, None) if plugin is enabled
        (None, (json_response, status_code)) if plugin disabled or unavailable
    """
    config_store = getattr(current_app, "config_store", None)
    if not config_store:
        return None, (jsonify({"error": "Plugin system not available"}), 503)

    entry = config_store.get_by_name(plugin_name)
    if not entry or entry.status != "enabled":
        return None, (jsonify({"error": "Plugin not enabled"}), 404)

    config = config_store.get_config(plugin_name)
    return config, None


def validate_invoice_for_payment(invoice_id_str, user_id):
    """Validate invoice exists, is PENDING, and belongs to user.

    Every payment create-session route calls this after parsing request body.
    Uses DI container from current_app for request-scoped repository.

    Returns:
        (invoice, None) if valid
        (None, (json_response, status_code)) if invalid
    """
    try:
        invoice_uuid = (
            UUID(invoice_id_str) if isinstance(invoice_id_str, str) else invoice_id_str
        )
    except (ValueError, TypeError):
        return None, (jsonify({"error": "Invalid invoice_id format"}), 400)

    container = current_app.container
    invoice_repo = container.invoice_repository()
    invoice = invoice_repo.find_by_id(invoice_uuid)

    if not invoice:
        return None, (jsonify({"error": "Invoice not found"}), 404)
    if invoice.status.value != "PENDING":
        return None, (
            jsonify({"error": f"Invoice is {invoice.status.value}, expected PENDING"}),
            400,
        )
    if str(invoice.user_id) != str(user_id):
        return None, (jsonify({"error": "Invoice does not belong to this user"}), 403)

    return invoice, None


def emit_payment_captured(
    invoice_id,
    payment_reference,
    amount,
    currency,
    provider,
    transaction_id="",
    metadata=None,
):
    """Emit PaymentCapturedEvent -- the ONLY action a webhook handler should take.

    Event-driven: the webhook route emits this event and returns 200.
    PaymentCapturedHandler handles all activation (invoice->PAID, subscription->ACTIVE, etc.)
    The payment plugin NEVER acts directly on domain objects.

    ``metadata``: optional ``{namespace: {...}}`` payload merged into the
    invoice's free-form ``metadata`` JSON column by the handler. Each plugin
    owns its own top-level namespace key (e.g. ``{"stripe": {...}}``,
    ``{"paypal": {...}}``, ``{"tokens_paid": {...}}``) — the core handler
    does not interpret the inner shape.

    Returns:
        EventResult from the handler chain
    """
    logger.info(
        "emit_payment_captured: invoice=%s provider=%s ref=%s amount=%s",
        invoice_id,
        provider,
        payment_reference,
        amount,
    )
    event = PaymentCapturedEvent(
        invoice_id=invoice_id,
        payment_reference=payment_reference,
        amount=amount,
        currency=currency,
        provider=provider,
        transaction_id=transaction_id,
        metadata=metadata or {},
    )
    container = current_app.container
    result = container.event_dispatcher().emit(event)
    if not result.success:
        logger.error("PaymentCapturedEvent handler failed: %s", result.error)
    else:
        logger.info(
            "PaymentCapturedEvent processed successfully for invoice %s", invoice_id
        )
    return result


def emit_payment_authorized(
    invoice_id, payment_reference, amount, currency, provider, payment_intent_id=""
):
    """Emit PaymentAuthorizedEvent — card authorized, not yet captured.

    Called by payment provider webhooks when capture_method is manual.
    """
    logger.info(
        "emit_payment_authorized: invoice=%s provider=%s pi=%s amount=%s",
        invoice_id,
        provider,
        payment_intent_id,
        amount,
    )
    event = PaymentAuthorizedEvent(
        invoice_id=invoice_id,
        payment_reference=payment_reference,
        amount=amount,
        currency=currency,
        provider=provider,
        payment_intent_id=payment_intent_id,
    )
    container = current_app.container
    result = container.event_dispatcher().emit(event)
    if not result.success:
        logger.error("PaymentAuthorizedEvent handler failed: %s", result.error)
    return result


def determine_capture_method(invoice):
    """Determine capture method based on line item plugin configs.

    Returns "manual" if any line item belongs to a plugin configured for
    authorize-only, otherwise "auto" (immediate capture).
    """
    for item in invoice.line_items:
        extra = getattr(item, "extra_data", None) or {}
        plugin_name = extra.get("plugin")
        if not plugin_name:
            continue

        config_store = getattr(current_app, "config_store", None)
        if not config_store:
            continue

        plugin_config = config_store.get_config(plugin_name)
        if plugin_config and plugin_config.get("capture_mode") == "manual":
            return "manual"

    return "auto"


def determine_session_mode(invoice):
    """Check invoice line items to determine payment mode.

    Returns "subscription" if any line item is recurring, "payment"
    otherwise. Recurrence is owned by the line-item handler registry —
    core no longer knows what a subscription is.
    """
    from vbwd.events.line_item_registry import line_item_registry

    for item in invoice.line_items:
        if line_item_registry.is_recurring_line_item(item):
            return "subscription"
    return "payment"


# ── Redirect-URL builder (S21) ────────────────────────────────────────────


def resolve_frontend_base(request) -> str:
    """Derive the web frontend's base URL from request headers.

    Stripe/PayPal/YooKassa all need the same fallback chain:
    Origin → Referer's pre-``/pay`` segment → ``request.host_url``.
    """
    return (
        request.headers.get("Origin")
        or request.headers.get("Referer", "").rstrip("/").rsplit("/pay", 1)[0]
        or request.host_url.rstrip("/")
    )


def build_provider_redirect_urls(
    request,
    provider: str,
    success_query: str = "",
    *,
    ios_deep_link: bool = False,
) -> tuple[str, str]:
    """Build ``(success_url, cancel_url)`` for a payment provider's checkout.

    Honours ``X-Client-Platform: ios|macos`` (when ``ios_deep_link=True``)
    to emit a ``vbwd://<provider>-callback/...`` deep link that the iOS /
    macOS app can intercept via ``ASWebAuthenticationSession``. Otherwise
    falls back to the web base from :func:`resolve_frontend_base`.

    ``success_query`` is appended verbatim to the success URL — pass the
    provider-specific session-id placeholder (e.g.
    ``"?session_id={CHECKOUT_SESSION_ID}"`` for Stripe).
    """
    if ios_deep_link:
        platform = request.headers.get("X-Client-Platform", "").lower()
        if platform in ("ios", "macos"):
            return (
                f"vbwd://{provider}-callback/success{success_query}",
                f"vbwd://{provider}-callback/cancel",
            )
    base = resolve_frontend_base(request)
    return (
        f"{base}/pay/{provider}/success{success_query}",
        f"{base}/pay/{provider}/cancel",
    )
