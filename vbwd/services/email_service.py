"""Email service for sending emails via SMTP."""
import smtplib
import logging
import re
from typing import Optional, List, Dict, Any, Tuple
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime
from jinja2 import (
    Environment,
    FileSystemLoader,
    ChoiceLoader,
    TemplateNotFound as Jinja2TemplateNotFound,
)

from vbwd.services.asset_storage import asset_dir

logger = logging.getLogger(__name__)


class EmailConfigError(Exception):
    """Raised when email configuration is invalid."""

    pass


class TemplateNotFoundError(Exception):
    """Raised when email template is not found."""

    pass


class EmailResult:
    """Result of an email operation."""

    def __init__(self, success: bool, error: Optional[str] = None):
        """
        Initialize email result.

        Args:
            success: Whether the operation succeeded.
            error: Error message if failed.
        """
        self.success = success
        self.error = error


class EmailService:
    """Service for sending emails via SMTP."""

    # Email validation pattern
    EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        from_email: str,
        from_name: str = "VBWD",
        template_dir: str = "src/templates/email",
    ):
        """
        Initialize email service.

        Args:
            smtp_host: SMTP server hostname.
            smtp_port: SMTP server port.
            smtp_user: SMTP authentication username.
            smtp_password: SMTP authentication password.
            from_email: Default sender email address.
            from_name: Default sender name.
            template_dir: Directory containing email templates.

        Raises:
            EmailConfigError: If configuration is invalid.
        """
        # Validate required config
        self._validate_config(
            smtp_host, smtp_port, smtp_user, smtp_password, from_email
        )

        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_user = smtp_user
        self._smtp_password = smtp_password
        self._from_email = from_email
        self._from_name = from_name

        # Loader order (first match wins):
        #   1. admin overrides in var/assets/core/email/templates (host-mounted,
        #      editable per deployment — an operator-supplied template WINS),
        #   2. the bundled defaults shipped in the image,
        #   3. any plugin-contributed dirs appended via register_template_path
        #      (ChoiceLoader so feature plugins own their own email templates
        #      without core knowing them — e.g. the subscription plugin's
        #      activation/cancellation mails).
        # FileSystemLoader of a missing dir is harmless, so an absent override
        # dir (empty var) simply falls through to the bundled defaults.
        self._template_dirs: list = [
            asset_dir("core", "email", "templates"),
            template_dir,
        ]
        self._template_env: Optional[Environment] = None
        self._build_template_env()

    def _build_template_env(self) -> None:
        try:
            self._template_env = Environment(
                loader=ChoiceLoader([FileSystemLoader(d) for d in self._template_dirs]),
                autoescape=True,
            )
        except Exception as e:
            logger.warning(f"Could not load template directories: {e}")

    def register_template_path(self, template_dir: str) -> None:
        """Add a (plugin) template directory. Later registrations are searched
        after the core dir. Plugins call this on enable so their own email
        templates resolve through the generic render/send primitives."""
        if template_dir not in self._template_dirs:
            self._template_dirs.append(template_dir)
            self._build_template_env()

    def _validate_config(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        from_email: str,
    ) -> None:
        """Validate SMTP configuration."""
        errors = []

        if not smtp_host:
            errors.append("smtp_host is required")
        if not smtp_port:
            errors.append("smtp_port is required")
        if not smtp_user:
            errors.append("smtp_user is required")
        if not smtp_password:
            errors.append("smtp_password is required")
        if not from_email:
            errors.append("from_email is required")

        if errors:
            raise EmailConfigError(f"Invalid configuration: {', '.join(errors)}")

    def _validate_email(self, email: str) -> bool:
        """Validate email address format."""
        if not email:
            return False
        return bool(self.EMAIL_REGEX.match(email))

    def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        attachments: Optional[List[Tuple[str, bytes, str]]] = None,
    ) -> EmailResult:
        """
        Send email via SMTP.

        Args:
            to_email: Recipient email address.
            subject: Email subject.
            body_text: Plain text body.
            body_html: Optional HTML body.
            attachments: List of (filename, data, mime_type) tuples.

        Returns:
            EmailResult with success status.
        """
        # Validate recipient email
        if not self._validate_email(to_email):
            return EmailResult(success=False, error="Invalid recipient email address")

        try:
            # Create message
            if body_html or attachments:
                msg = MIMEMultipart("alternative")
            else:
                msg = MIMEMultipart()

            msg["From"] = f"{self._from_name} <{self._from_email}>"
            msg["To"] = to_email
            msg["Subject"] = subject

            # Add plain text body
            text_part = MIMEText(body_text, "plain", "utf-8")
            msg.attach(text_part)

            # Add HTML body if provided
            if body_html:
                html_part = MIMEText(body_html, "html", "utf-8")
                msg.attach(html_part)

            # Add attachments if provided
            if attachments:
                for filename, data, mime_type in attachments:
                    attachment = MIMEApplication(data)
                    attachment.add_header(
                        "Content-Disposition", "attachment", filename=filename
                    )
                    attachment.add_header("Content-Type", mime_type)
                    msg.attach(attachment)

            # Send email
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                server.starttls()
                server.login(self._smtp_user, self._smtp_password)
                server.sendmail(self._from_email, to_email, msg.as_string())

            logger.info(f"Email sent successfully to {to_email}")
            return EmailResult(success=True)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to send email to {to_email}: {error_msg}")
            return EmailResult(success=False, error=error_msg)

    def render_template(
        self, template_name: str, context: Dict[str, Any]
    ) -> Tuple[str, str]:
        """
        Render email template.

        Args:
            template_name: Name of the template (without extension).
            context: Template context variables.

        Returns:
            Tuple of (plain_text, html).

        Raises:
            TemplateNotFoundError: If template is not found.
        """
        if not self._template_env:
            raise TemplateNotFoundError("Template directory not configured")

        try:
            # Try to load text template
            text_template = self._template_env.get_template(f"{template_name}.txt")
            text_content = text_template.render(**context)
        except Jinja2TemplateNotFound:
            raise TemplateNotFoundError(f"Template '{template_name}.txt' not found")

        try:
            # Try to load HTML template
            html_template = self._template_env.get_template(f"{template_name}.html")
            html_content = html_template.render(**context)
        except Jinja2TemplateNotFound:
            raise TemplateNotFoundError(f"Template '{template_name}.html' not found")

        return text_content, html_content

    def send_welcome_email(self, to_email: str, first_name: str) -> EmailResult:
        """
        Send welcome email to new user.

        Args:
            to_email: Recipient email address.
            first_name: User's first name.

        Returns:
            EmailResult with success status.
        """
        try:
            context = {
                "first_name": first_name,
                "login_url": "https://vbwd.com/login",
                "year": datetime.now().year,
            }
            text_body, html_body = self.render_template("welcome", context)

            return self.send_email(
                to_email=to_email,
                subject="Welcome to VBWD!",
                body_text=text_body,
                body_html=html_body,
            )
        except TemplateNotFoundError as e:
            logger.error(f"Template error: {e}")
            return EmailResult(success=False, error=str(e))

    # S25 — removed ``send_invoice``: no callers (grep proves it), and
    # ``send_template("invoice", context)`` covers any future invoice mail
    # path with attachments via ``send_email`` directly.

    def send_template(
        self,
        to: str,
        template: str,
        context: Dict[str, Any],
        subject: Optional[str] = None,
    ) -> EmailResult:
        """
        Send templated email.

        Generic method for sending emails using templates.

        Args:
            to: Recipient email address.
            template: Template name (without extension).
            context: Template context variables.
            subject: Optional custom subject (defaults based on template).

        Returns:
            EmailResult with success status.
        """
        # Default subjects for known templates
        default_subjects = {
            "password_reset": "Reset Your Password",
            "password_changed": "Your Password Has Been Changed",
            "welcome": "Welcome to VBWD!",
        }

        try:
            text_body, html_body = self.render_template(template, context)
            email_subject = subject or default_subjects.get(
                template, f"VBWD - {template.replace('_', ' ').title()}"
            )

            return self.send_email(
                to_email=to,
                subject=email_subject,
                body_text=text_body,
                body_html=html_body,
            )
        except TemplateNotFoundError as e:
            logger.error(f"Template error: {e}")
            return EmailResult(success=False, error=str(e))
