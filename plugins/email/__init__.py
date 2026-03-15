"""Email plugin — transactional email templates, SMTP transport, event handlers."""
from typing import Optional, Dict, Any, TYPE_CHECKING
from src.plugins.base import BasePlugin, PluginMetadata

if TYPE_CHECKING:
    from flask import Blueprint

DEFAULT_CONFIG: Dict[str, Any] = {
    "smtp_host": "localhost",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_use_tls": True,
    "smtp_from_email": "noreply@example.com",
    "smtp_from_name": "VBWD",
    "active_sender": "smtp",
    "log_sends": False,
}


class EmailPlugin(BasePlugin):
    """Transactional email plugin.

    Provides:
    - EmailTemplate DB model (event-keyed HTML/text templates)
    - SmtpEmailSender transport
    - EmailSenderRegistry (swappable transport container)
    - EmailService (Jinja2 rendering + dispatch)
    - Admin API routes under /api/v1/admin/email/
    - Domain event subscriptions for subscription + user lifecycle

    Class MUST be defined in __init__.py (not re-exported) due to
    discovery check obj.__module__ != full_module in manager.py.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="email",
            version="1.0.0",
            author="VBWD Team",
            description="Transactional email — templates, SMTP, event-driven dispatch",
            dependencies=[],
        )

    def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        merged = {**DEFAULT_CONFIG}
        if config:
            merged.update(config)
        super().initialize(merged)

    def get_blueprint(self) -> Optional["Blueprint"]:
        from plugins.email.src.routes import email_bp

        return email_bp

    def get_url_prefix(self) -> Optional[str]:
        return ""

    def on_enable(self) -> None:
        pass

    def register_event_handlers(self, bus: Any) -> None:
        """Subscribe email handlers to EventBus.

        Called by PluginManager after on_enable(). Replaces the broken
        ``event_dispatcher.subscribe()`` pattern from the old handlers.py.
        """
        try:
            cfg = self._config or {}
            from plugins.email.src.handlers import register_handlers

            register_handlers(bus, cfg)
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "[email] Event handlers not registered — check config"
            )

    def on_disable(self) -> None:
        pass
