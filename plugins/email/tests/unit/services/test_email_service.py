"""Unit tests for EmailService."""
import pytest
from unittest.mock import MagicMock

from plugins.email.src.services.email_service import EmailService, TemplateRenderError
from plugins.email.src.services.sender_registry import EmailSenderRegistry
from plugins.email.src.services.base_sender import EmailSendError


def _make_template(event_type="subscription.activated", is_active=True):
    tpl = MagicMock()
    tpl.event_type = event_type
    tpl.subject = "Hello {{ user_name }}"
    tpl.html_body = "<p>Hi {{ user_name }}</p>"
    tpl.text_body = "Hi {{ user_name }}"
    tpl.is_active = is_active
    return tpl


def _make_registry_with_sender():
    sender = MagicMock()
    sender.sender_id = "smtp"
    registry = EmailSenderRegistry()
    registry.register(sender)
    registry.set_active("smtp")
    return registry, sender


class TestEmailService:
    def _make_svc(self, template=None, active=True):
        registry, sender = _make_registry_with_sender()
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = (
            template if template is not None else _make_template(is_active=active)
        )
        return EmailService(registry=registry, db_session=session), sender

    def test_send_event_calls_sender(self):
        svc, sender = self._make_svc()
        result = svc.send_event(
            "subscription.activated",
            "alice@example.com",
            {"user_name": "Alice"},
        )
        assert result is True
        sender.send.assert_called_once()
        msg = sender.send.call_args[0][0]
        assert msg.to_address == "alice@example.com"
        assert "Alice" in msg.subject
        assert "Alice" in msg.html_body

    def test_send_event_returns_false_when_inactive(self):
        svc, sender = self._make_svc(active=False)
        result = svc.send_event(
            "subscription.activated",
            "alice@example.com",
            {"user_name": "Alice"},
        )
        assert result is False
        sender.send.assert_not_called()

    def test_send_event_returns_false_when_template_not_found(self):
        registry, sender = _make_registry_with_sender()
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        svc = EmailService(registry=registry, db_session=session)
        result = svc.send_event(
            "subscription.activated",
            "alice@example.com",
            {"user_name": "Alice"},
        )
        assert result is False
        sender.send.assert_not_called()

    def test_send_event_propagates_send_error(self):
        svc, sender = self._make_svc()
        sender.send.side_effect = EmailSendError("SMTP down")
        with pytest.raises(EmailSendError):
            svc.send_event(
                "subscription.activated",
                "alice@example.com",
                {"user_name": "Alice"},
            )

    def test_render_preview_returns_rendered_content(self):
        svc, _ = self._make_svc()
        result = svc.render_preview(
            "subscription.activated",
            {"user_name": "Bob"},
        )
        assert result["subject"] == "Hello Bob"
        assert "Bob" in result["html_body"]
        assert "Bob" in result["text_body"]

    def test_render_preview_empty_when_not_found(self):
        registry, _ = _make_registry_with_sender()
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        svc = EmailService(registry=registry, db_session=session)
        result = svc.render_preview("nonexistent", {})
        assert result == {"subject": "", "html_body": "", "text_body": ""}

    def test_template_render_error_on_bad_syntax(self):
        registry, _ = _make_registry_with_sender()
        session = MagicMock()
        tpl = _make_template()
        tpl.subject = "{{ unclosed"
        session.query.return_value.filter_by.return_value.first.return_value = tpl
        svc = EmailService(registry=registry, db_session=session)
        with pytest.raises(TemplateRenderError):
            svc.send_event("subscription.activated", "x@x.com", {})
