"""Unit tests for SmtpEmailSender."""
import pytest
from unittest.mock import MagicMock, patch

from plugins.email.src.services.smtp_sender import SmtpEmailSender
from plugins.email.src.services.base_sender import EmailMessage, EmailSendError


def _make_message(**kwargs):
    defaults = {
        "to_address": "test@example.com",
        "subject": "Test subject",
        "html_body": "<p>Test</p>",
        "text_body": "Test",
    }
    defaults.update(kwargs)
    return EmailMessage(**defaults)


class TestSmtpEmailSender:
    def test_sender_id(self):
        sender = SmtpEmailSender(host="localhost")
        assert sender.sender_id == "smtp"

    def test_send_calls_starttls_by_default(self):
        sender = SmtpEmailSender(
            host="smtp.example.com",
            port=587,
            use_tls=True,
        )
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_smtp
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            sender.send(_make_message())
            mock_smtp.starttls.assert_called_once()
            mock_smtp.send_message.assert_called_once()

    def test_send_calls_login_when_credentials_provided(self):
        sender = SmtpEmailSender(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
        )
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_smtp
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            sender.send(_make_message())
            mock_smtp.login.assert_called_once_with("user", "pass")

    def test_send_skips_login_without_credentials(self):
        sender = SmtpEmailSender(host="localhost", port=1025, use_tls=False)
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_smtp
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            sender.send(_make_message())
            mock_smtp.login.assert_not_called()

    def test_send_raises_email_send_error_on_smtp_exception(self):
        import smtplib

        sender = SmtpEmailSender(host="smtp.example.com")
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.side_effect = smtplib.SMTPConnectError(
                421, "Connection refused"
            )
            with pytest.raises(EmailSendError):
                sender.send(_make_message())

    def test_send_raises_email_send_error_on_os_error(self):
        sender = SmtpEmailSender(host="smtp.example.com")
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.side_effect = OSError("Network unreachable")
            with pytest.raises(EmailSendError):
                sender.send(_make_message())

    def test_from_address_uses_message_override(self):
        sender = SmtpEmailSender(
            host="localhost", port=1025, use_tls=False, from_address="default@x.com"
        )
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_smtp
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            msg = _make_message(from_address="custom@x.com", from_name="Custom")
            sender.send(msg)
            mime = mock_smtp.send_message.call_args[0][0]
            assert "custom@x.com" in mime["From"]

    def test_cc_included_in_mime(self):
        sender = SmtpEmailSender(host="localhost", port=1025, use_tls=False)
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_smtp
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            msg = _make_message(cc=["cc1@x.com", "cc2@x.com"])
            sender.send(msg)
            mime = mock_smtp.send_message.call_args[0][0]
            assert "cc1@x.com" in mime["Cc"]
