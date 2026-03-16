"""SmtpEmailSender — sends email via SMTP using stdlib smtplib."""
from __future__ import annotations
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from plugins.email.src.services.base_sender import (
    EmailMessage,
    EmailSendError,
    IEmailSender,
)


class SmtpEmailSender:
    """Concrete SMTP transport.

    Parameters
    ----------
    host        : SMTP server hostname
    port        : SMTP port (default 587 for STARTTLS)
    username    : SMTP auth username (optional)
    password    : SMTP auth password (optional)
    use_tls     : True = STARTTLS (default), False = plain, 'ssl' = SMTP_SSL
    from_address: envelope From address
    from_name   : display name in From header
    """

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = True,
        from_address: str = "noreply@example.com",
        from_name: str = "VBWD",
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._from_address = from_address
        self._from_name = from_name

    # IEmailSender contract --------------------------------------------

    @property
    def sender_id(self) -> str:
        return "smtp"

    def send(self, message: EmailMessage) -> None:
        """Build MIME message and deliver via SMTP.  Raises EmailSendError."""
        mime = self._build_mime(message)
        try:
            self._deliver(mime, message.to_address)
        except smtplib.SMTPException as exc:
            raise EmailSendError(f"SMTP delivery failed: {exc}") from exc
        except OSError as exc:
            raise EmailSendError(f"SMTP connection error: {exc}") from exc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_mime(self, message: EmailMessage) -> MIMEMultipart:
        mime = MIMEMultipart("alternative")
        from_addr = message.from_address or self._from_address
        from_name = message.from_name or self._from_name
        mime["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
        mime["To"] = message.to_address
        mime["Subject"] = message.subject
        if message.reply_to:
            mime["Reply-To"] = message.reply_to
        if message.cc:
            mime["Cc"] = ", ".join(message.cc)
        for k, v in message.headers.items():
            mime[k] = v
        if message.text_body:
            mime.attach(MIMEText(message.text_body, "plain", "utf-8"))
        mime.attach(MIMEText(message.html_body, "html", "utf-8"))
        return mime

    def _deliver(self, mime: MIMEMultipart, to_address: str) -> None:
        if self._use_tls == "ssl":
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(self._host, self._port, context=ctx) as smtp:
                self._auth(smtp)
                smtp.send_message(mime)
        else:
            with smtplib.SMTP(self._host, self._port) as smtp:
                if self._use_tls:
                    smtp.starttls()
                self._auth(smtp)
                smtp.send_message(mime)

    def _auth(self, smtp: smtplib.SMTP) -> None:
        if self._username and self._password:
            smtp.login(self._username, self._password)


# Make type-checker happy: confirm structural subtyping
assert isinstance(SmtpEmailSender.__new__(SmtpEmailSender), IEmailSender)  # type: ignore[arg-type]
