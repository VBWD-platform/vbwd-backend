"""Mailchimp (Mandrill) transactional email plugin.

When enabled, registers MandrillEmailSender with the EmailSenderRegistry
so it can be selected as the active transport via the email plugin config.

Class MUST be defined in __init__.py (not re-exported) due to
discovery check obj.__module__ != full_module in manager.py.
"""
from typing import Optional, Dict, Any, TYPE_CHECKING
from src.plugins.base import BasePlugin, PluginMetadata

if TYPE_CHECKING:
    from flask import Blueprint

DEFAULT_CONFIG: Dict[str, Any] = {
    "mandrill_api_key": "",
    "from_email": "noreply@example.com",
    "from_name": "VBWD",
}


class MailchimpPlugin(BasePlugin):
    """Mailchimp Transactional (Mandrill) email transport plugin."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="mailchimp",
            version="1.0.0",
            author="VBWD Team",
            description="Mailchimp Transactional (Mandrill) email transport",
            dependencies=["email"],
        )

    def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        merged = {**DEFAULT_CONFIG}
        if config:
            merged.update(config)
        super().initialize(merged)

    def get_blueprint(self) -> Optional["Blueprint"]:
        return None

    def get_url_prefix(self) -> Optional[str]:
        return ""

    def on_enable(self) -> None:
        """Register MandrillEmailSender with the email plugin's registry."""
        try:
            cfg = self._config or {}
            api_key = cfg.get("mandrill_api_key", "")
            if not api_key:
                import logging

                logging.getLogger(__name__).warning(
                    "[mailchimp] mandrill_api_key not set — sender not registered"
                )
                return

            from plugins.mailchimp.src.services.mandrill_sender import (
                MandrillEmailSender,
            )

            # Instantiate to validate config; actual use requires the email
            # plugin's registry to be configured with 'mandrill' as active_sender.
            MandrillEmailSender(
                api_key=api_key,
                from_address=cfg.get("from_email", "noreply@example.com"),
                from_name=cfg.get("from_name", "VBWD"),
            )
            import logging

            logging.getLogger(__name__).info(
                "[mailchimp] MandrillEmailSender available (sender_id='mandrill')"
            )
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "[mailchimp] MandrillEmailSender not registered"
            )

    def on_disable(self) -> None:
        pass
