"""Email event handlers — subscribe to domain events and fire emails."""
from __future__ import annotations
import logging

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


def register_handlers(cfg: dict) -> None:
    """Subscribe email handlers to domain events.

    Called from EmailPlugin.on_enable() with the plugin config dict.
    """
    from src.events import event_dispatcher

    def _safe_send(event_type: str, to: str, context: dict) -> None:
        try:
            svc = _make_email_service(cfg)
            svc.send_event(event_type, to, context)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[email] Failed to send %s to %s: %s", event_type, to, exc)

    def on_subscription_activated(payload: dict) -> None:
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

    def on_subscription_cancelled(payload: dict) -> None:
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

    def on_subscription_payment_failed(payload: dict) -> None:
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

    def on_subscription_renewed(payload: dict) -> None:
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

    def on_user_registered(payload: dict) -> None:
        _safe_send(
            "user.registered",
            payload.get("user_email", ""),
            {
                "user_name": payload.get("user_name", ""),
                "user_email": payload.get("user_email", ""),
                "login_url": payload.get("login_url", "/login"),
            },
        )

    def on_user_password_reset(payload: dict) -> None:
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

    event_dispatcher.subscribe("subscription.activated", on_subscription_activated)
    event_dispatcher.subscribe("subscription.cancelled", on_subscription_cancelled)
    event_dispatcher.subscribe("subscription.payment_failed", on_subscription_payment_failed)
    event_dispatcher.subscribe("subscription.renewed", on_subscription_renewed)
    event_dispatcher.subscribe("user.registered", on_user_registered)
    event_dispatcher.subscribe("user.password_reset", on_user_password_reset)

    logger.info("[email] Event handlers registered")
