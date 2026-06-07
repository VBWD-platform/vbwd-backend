"""Tests for email service."""
import pytest
from unittest.mock import patch, MagicMock


class TestEmailServiceConfiguration:
    """Tests for EmailService configuration."""

    def test_service_initializes_with_smtp_config(self):
        """Service initializes with valid SMTP configuration."""
        from vbwd.services.email_service import EmailService

        service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
            from_name="VBWD",
        )

        assert service._smtp_host == "smtp.example.com"
        assert service._smtp_port == 587
        assert service._from_email == "noreply@example.com"

    def test_service_validates_smtp_config(self):
        """Service validates required SMTP config."""
        from vbwd.services.email_service import EmailService, EmailConfigError

        with pytest.raises(EmailConfigError) as exc_info:
            EmailService(
                smtp_host="",
                smtp_port=587,
                smtp_user="user@example.com",
                smtp_password="password",
                from_email="noreply@example.com",
            )

        assert "smtp_host" in str(exc_info.value).lower()

    def test_service_handles_missing_config(self):
        """Service raises error for missing config."""
        from vbwd.services.email_service import EmailService, EmailConfigError

        with pytest.raises(EmailConfigError):
            EmailService(
                smtp_host=None,
                smtp_port=None,
                smtp_user=None,
                smtp_password=None,
                from_email=None,
            )


class TestEmailServiceSend:
    """Tests for EmailService send functionality."""

    @pytest.fixture
    def email_service(self):
        """Create email service with mocked SMTP."""
        from vbwd.services.email_service import EmailService

        return EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
            from_name="VBWD",
        )

    @patch("vbwd.services.email_service.smtplib.SMTP")
    def test_send_email_success(self, mock_smtp_class, email_service):
        """Send email successfully."""
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = email_service.send_email(
            to_email="recipient@example.com",
            subject="Test Subject",
            body_text="Test body",
        )

        assert result.success is True
        assert result.error is None
        mock_smtp.sendmail.assert_called_once()

    @patch("vbwd.services.email_service.smtplib.SMTP")
    def test_send_email_with_html(self, mock_smtp_class, email_service):
        """Send email with HTML body."""
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = email_service.send_email(
            to_email="recipient@example.com",
            subject="Test Subject",
            body_text="Test body",
            body_html="<html><body>Test body</body></html>",
        )

        assert result.success is True

    @patch("vbwd.services.email_service.smtplib.SMTP")
    def test_send_email_with_attachment(self, mock_smtp_class, email_service):
        """Send email with attachment."""
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        pdf_content = b"%PDF-1.4 test content"
        result = email_service.send_email(
            to_email="recipient@example.com",
            subject="Test Subject",
            body_text="Test body",
            attachments=[("invoice.pdf", pdf_content, "application/pdf")],
        )

        assert result.success is True

    @patch("vbwd.services.email_service.smtplib.SMTP")
    def test_send_email_failure_logged(self, mock_smtp_class, email_service):
        """Failed email send is logged and returns error."""
        mock_smtp = MagicMock()
        mock_smtp.sendmail.side_effect = Exception("SMTP error")
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = email_service.send_email(
            to_email="recipient@example.com",
            subject="Test Subject",
            body_text="Test body",
        )

        assert result.success is False
        assert "SMTP error" in result.error

    def test_send_email_invalid_recipient(self, email_service):
        """Invalid recipient email returns error."""
        result = email_service.send_email(
            to_email="invalid-email", subject="Test Subject", body_text="Test body"
        )

        assert result.success is False
        assert "invalid" in result.error.lower()


class TestEmailServiceTemplates:
    """Tests for EmailService template rendering."""

    @pytest.fixture
    def email_service_with_templates(self, tmp_path):
        """Create email service with test templates."""
        from vbwd.services.email_service import EmailService

        # Create test templates
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        # Create base template
        base_html = template_dir / "base.html"
        base_html.write_text(
            """<!DOCTYPE html>
<html><body>{% block content %}{% endblock %}</body></html>"""
        )

        # Create welcome template
        welcome_html = template_dir / "welcome.html"
        welcome_html.write_text(
            """{% extends "base.html" %}
{% block content %}<h1>Welcome {{ first_name }}!</h1>{% endblock %}"""
        )

        welcome_txt = template_dir / "welcome.txt"
        welcome_txt.write_text("Welcome {{ first_name }}!")

        return EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
            template_dir=str(template_dir),
        )

    def test_render_template_success(self, email_service_with_templates):
        """Render template successfully."""
        text, html = email_service_with_templates.render_template(
            template_name="welcome", context={"first_name": "John"}
        )

        assert "Welcome John!" in text
        assert "Welcome John!" in html

    def test_render_template_not_found(self, email_service_with_templates):
        """Render non-existent template raises error."""
        from vbwd.services.email_service import TemplateNotFoundError

        with pytest.raises(TemplateNotFoundError):
            email_service_with_templates.render_template(
                template_name="nonexistent", context={}
            )

    def test_render_template_with_context(self, email_service_with_templates):
        """Render template with context variables."""
        text, html = email_service_with_templates.render_template(
            template_name="welcome",
            context={"first_name": "Alice", "extra_var": "ignored"},
        )

        assert "Alice" in text
        assert "Alice" in html


class TestEmailServiceVarAssetsOverride:
    """Admin-supplied templates in ``var/assets/core/email/templates`` WIN
    over the bundled defaults; absence of an override is harmless."""

    def _make_service(self, bundled_dir):
        from vbwd.services.email_service import EmailService

        return EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
            template_dir=str(bundled_dir),
        )

    def test_override_dir_wins_over_bundled(self, monkeypatch, tmp_path):
        var_dir = tmp_path / "var"
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "welcome.txt").write_text("bundled {{ first_name }}")
        (bundled / "welcome.html").write_text("<p>bundled {{ first_name }}</p>")
        override = var_dir / "assets" / "core" / "email" / "templates"
        override.mkdir(parents=True)
        (override / "welcome.txt").write_text("override {{ first_name }}")
        (override / "welcome.html").write_text("<p>override {{ first_name }}</p>")

        monkeypatch.setenv("VBWD_VAR_DIR", str(var_dir))
        service = self._make_service(bundled)
        text, html = service.render_template("welcome", {"first_name": "Jo"})
        assert "override Jo" in text
        assert "override Jo" in html

    def test_bundled_renders_without_override(self, monkeypatch, tmp_path):
        var_dir = tmp_path / "var"  # exists but no assets dir at all
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "welcome.txt").write_text("bundled {{ first_name }}")
        (bundled / "welcome.html").write_text("<p>bundled {{ first_name }}</p>")

        monkeypatch.setenv("VBWD_VAR_DIR", str(var_dir))
        service = self._make_service(bundled)
        text, html = service.render_template("welcome", {"first_name": "Jo"})
        assert "bundled Jo" in text
        assert "bundled Jo" in html

    def test_plugin_registered_path_still_appended_last(self, monkeypatch, tmp_path):
        var_dir = tmp_path / "var"
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        plugin = tmp_path / "plugin"
        plugin.mkdir()
        # Only the plugin dir has this template; it must resolve.
        (plugin / "plugin_only.txt").write_text("plugin {{ first_name }}")
        (plugin / "plugin_only.html").write_text("<p>plugin {{ first_name }}</p>")

        monkeypatch.setenv("VBWD_VAR_DIR", str(var_dir))
        service = self._make_service(bundled)
        service.register_template_path(str(plugin))
        text, _html = service.render_template("plugin_only", {"first_name": "Jo"})
        assert "plugin Jo" in text


class TestEmailServiceConvenienceMethods:
    """Tests for EmailService convenience methods."""

    @pytest.fixture
    def email_service(self, tmp_path):
        """Create email service with test templates."""
        from vbwd.services.email_service import EmailService

        # Create minimal templates
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        for name in [
            "welcome",
            "subscription_activated",
            "subscription_cancelled",
            "payment_receipt",
            "payment_failed",
            "invoice",
            "renewal_reminder",
        ]:
            html_file = template_dir / f"{name}.html"
            html_file.write_text(f"<html>{{{{ first_name }}}} - {name}</html>")
            txt_file = template_dir / f"{name}.txt"
            txt_file.write_text(f"{{{{ first_name }}}} - {name}")

        return EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
            template_dir=str(template_dir),
        )

    @patch("vbwd.services.email_service.smtplib.SMTP")
    def test_send_welcome_email(self, mock_smtp_class, email_service):
        """Send welcome email to new user."""
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = email_service.send_welcome_email(
            to_email="user@example.com", first_name="John"
        )

        assert result.success is True

    # S25 — removed `test_send_invoice_email`: the `send_invoice` helper
    # had zero production callers and was deleted; this test only kept it
    # alive. Future invoice email work goes through `send_template`.
