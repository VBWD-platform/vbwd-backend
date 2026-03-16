"""Email event handlers — subscribe to EventBus and fire emails."""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.events.bus import EventBus

logger = logging.getLogger(__name__)


def _make_email_service(cfg: dict):
    """Factory: create EmailService with active registry + db.session."""
    from src.extensions import db
    from plugins.email.src.services.sender_registry import EmailSenderRegistry
    from plugins.email.src.services.smtp_sender import SmtpEmailSender
    from plugins.email.src.services.email_service import EmailService

    registry = EmailSenderRegistry()
    smtp = SmtpEmailSender(
        host=cfg.get("smtp_host", "localhost"),
        port=int(cfg.get("smtp_port", 587)),
        username=cfg.get("smtp_user") or None,
        password=cfg.get("smtp_password") or None,
        use_tls=cfg.get("smtp_use_tls", True),
        from_address=cfg.get("smtp_from_email", "noreply@example.com"),
        from_name=cfg.get("smtp_from_name", "VBWD"),
    )
    registry.register(smtp)
    registry.set_active("smtp")
    return EmailService(registry=registry, db_session=db.session)


def register_handlers(bus: "EventBus", cfg: dict) -> None:
    """Subscribe email handlers to EventBus events.

    Called from ``EmailPlugin.register_event_handlers(bus)`` with the plugin
    config dict.  Uses ``bus.subscribe()`` — no broken ``event_dispatcher``
    import needed.

    Args:
        bus: The ``EventBus`` singleton.
        cfg: Plugin configuration dict (SMTP settings etc.).
    """

    def _safe_send(event_type: str, to: str, context: dict) -> None:
        try:
            svc = _make_email_service(cfg)
            svc.send_event(event_type, to, context)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[email] Failed to send %s to %s: %s", event_type, to, exc)

    def on_subscription_activated(_name: str, payload: dict) -> None:
        _safe_send(
            "subscription.activated",
            payload.get("user_email", ""),
            {
                "user_name": payload.get("user_name", ""),
                "user_email": payload.get("user_email", ""),
                "plan_name": payload.get("plan_name", ""),
                "plan_price": payload.get("plan_price", ""),
                "billing_period": payload.get("billing_period", ""),
                "start_date": payload.get("start_date", ""),
                "next_billing_date": payload.get("next_billing_date", ""),
                "dashboard_url": payload.get("dashboard_url", "/dashboard"),
            },
        )

    def on_subscription_cancelled(_name: str, payload: dict) -> None:
        _safe_send(
            "subscription.cancelled",
            payload.get("user_email", ""),
            {
                "user_name": payload.get("user_name", ""),
                "user_email": payload.get("user_email", ""),
                "plan_name": payload.get("plan_name", ""),
                "end_date": payload.get("end_date", ""),
                "resubscribe_url": payload.get("resubscribe_url", "/plans"),
            },
        )

    def on_subscription_payment_failed(_name: str, payload: dict) -> None:
        _safe_send(
            "subscription.payment_failed",
            payload.get("user_email", ""),
            {
                "user_name": payload.get("user_name", ""),
                "user_email": payload.get("user_email", ""),
                "plan_name": payload.get("plan_name", ""),
                "amount": payload.get("amount", ""),
                "retry_date": payload.get("retry_date", ""),
                "update_payment_url": payload.get("update_payment_url", "/billing"),
            },
        )

    def on_subscription_renewed(_name: str, payload: dict) -> None:
        _safe_send(
            "subscription.renewed",
            payload.get("user_email", ""),
            {
                "user_name": payload.get("user_name", ""),
                "user_email": payload.get("user_email", ""),
                "plan_name": payload.get("plan_name", ""),
                "amount_charged": payload.get("amount_charged", ""),
                "next_billing_date": payload.get("next_billing_date", ""),
                "invoice_url": payload.get("invoice_url", "/invoices"),
            },
        )

    def on_user_registered(_name: str, payload: dict) -> None:
        _safe_send(
            "user.registered",
            payload.get("user_email", ""),
            {
                "user_name": payload.get("user_name", ""),
                "user_email": payload.get("user_email", ""),
                "login_url": payload.get("login_url", "/login"),
            },
        )

    def on_user_password_reset(_name: str, payload: dict) -> None:
        _safe_send(
            "user.password_reset",
            payload.get("user_email", ""),
            {
                "user_name": payload.get("user_name", ""),
                "user_email": payload.get("user_email", ""),
                "reset_url": payload.get("reset_url", ""),
                "expires_in": payload.get("expires_in", "1 hour"),
            },
        )

    def on_subscription_expired(_name: str, payload: dict) -> None:
        _safe_send(
            "subscription.expired",
            payload.get("user_email", ""),
            {
                "user_name": payload.get("user_name", ""),
                "user_email": payload.get("user_email", ""),
                "plan_name": payload.get("plan_name", ""),
                "resubscribe_url": payload.get("resubscribe_url", "/pricing"),
            },
        )

    def on_invoice_created(_name: str, payload: dict) -> None:
        _safe_send(
            "invoice.created",
            payload.get("user_email", ""),
            {
                "user_name": payload.get("user_name", ""),
                "user_email": payload.get("user_email", ""),
                "invoice_id": payload.get("invoice_id", ""),
                "amount": payload.get("amount", ""),
                "due_date": payload.get("due_date", ""),
                "invoice_url": payload.get("invoice_url", "/invoices"),
            },
        )

    def on_invoice_paid(_name: str, payload: dict) -> None:
        _safe_send(
            "invoice.paid",
            payload.get("user_email", ""),
            {
                "user_name": payload.get("user_name", ""),
                "user_email": payload.get("user_email", ""),
                "invoice_id": payload.get("invoice_id", ""),
                "amount": payload.get("amount", ""),
                "paid_date": payload.get("paid_date", ""),
                "invoice_url": payload.get("invoice_url", "/invoices"),
            },
        )

    def on_contact_form_received(_name: str, payload: dict) -> None:
        recipient = payload.get("recipient_email", "")
        if not recipient:
            logger.warning(
                "[email] contact_form.received: no recipient_email in payload"
            )
            return
        fields: list = payload.get("fields", [])
        rows = "\n".join(
            f"  {f.get('label', f.get('id', '?'))}: {f.get('value', '')}"
            for f in fields
        )
        _safe_send(
            "contact_form.received",
            recipient,
            {
                "widget_slug": payload.get("widget_slug", ""),
                "recipient_email": recipient,
                "remote_ip": payload.get("remote_ip", ""),
                "fields": fields,
                "fields_text": rows,
            },
        )

    bus.subscribe("subscription.activated", on_subscription_activated)
    bus.subscribe("subscription.cancelled", on_subscription_cancelled)
    bus.subscribe("subscription.expired", on_subscription_expired)
    bus.subscribe("subscription.payment_failed", on_subscription_payment_failed)
    bus.subscribe("subscription.renewed", on_subscription_renewed)
    bus.subscribe("invoice.created", on_invoice_created)
    bus.subscribe("invoice.paid", on_invoice_paid)
    bus.subscribe("user.registered", on_user_registered)
    bus.subscribe("user.password_reset", on_user_password_reset)
    bus.subscribe("contact_form.received", on_contact_form_received)

    logger.info("[email] Event handlers registered")
