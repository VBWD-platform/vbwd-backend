"""MandrillEmailSender — IEmailSender via Mailchimp Transactional (Mandrill) API.

Reference implementation demonstrating how to add a second transport
that is Liskov-substitutable for SmtpEmailSender.

Requires: pip install mailchimp-transactional
"""
from __future__ import annotations
import logging

from plugins.email.src.services.base_sender import (
    EmailMessage,
    EmailSendError,
    IEmailSender,
)

logger = logging.getLogger(__name__)


class MandrillEmailSender:
    """Sends email via the Mailchimp Transactional (Mandrill) HTTP API.

    Parameters
    ----------
    api_key      : Mandrill API key
    from_address : default From address
    from_name    : default From display name
    """

    def __init__(
        self,
        api_key: str,
        from_address: str = "noreply@example.com",
        from_name: str = "VBWD",
    ) -> None:
        if not api_key:
            raise ValueError("MandrillEmailSender requires a non-empty api_key")
        self._api_key = api_key
        self._from_address = from_address
        self._from_name = from_name

    # IEmailSender contract --------------------------------------------

    @property
    def sender_id(self) -> str:
        return "mandrill"

    def send(self, message: EmailMessage) -> None:
        """Deliver *message* via Mandrill API.  Raises EmailSendError."""
        try:
            import mailchimp_transactional as MailchimpTransactional  # type: ignore
            from mailchimp_transactional.api_client import ApiClientError  # type: ignore
        except ImportError as exc:
            raise EmailSendError(
                "mailchimp-transactional package is not installed. "
                "Run: pip install mailchimp-transactional"
            ) from exc

        client = MailchimpTransactional.Client(self._api_key)

        from_addr = message.from_address or self._from_address
        from_name = message.from_name or self._from_name

        payload = {
            "message": {
                "html": message.html_body,
                "text": message.text_body or None,
                "subject": message.subject,
                "from_email": from_addr,
                "from_name": from_name,
                "to": [{"email": message.to_address, "type": "to"}],
            }
        }

        try:
            result = client.messages.send(payload)
            logger.debug("[mandrill] send result: %s", result)
        except ApiClientError as exc:
            raise EmailSendError(f"Mandrill API error: {exc.text}") from exc
        except Exception as exc:
            raise EmailSendError(f"Mandrill delivery failed: {exc}") from exc


# Structural subtyping assertion (runtime-checkable Protocol)
assert isinstance(MandrillEmailSender.__new__(MandrillEmailSender), IEmailSender)  # type: ignore[arg-type]
