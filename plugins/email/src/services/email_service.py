"""EmailService — renders templates and dispatches via the active sender."""
from __future__ import annotations
from typing import Optional

from jinja2 import Environment, BaseLoader, TemplateSyntaxError

from plugins.email.src.services.base_sender import EmailMessage
from plugins.email.src.services.sender_registry import EmailSenderRegistry


class TemplateRenderError(Exception):
    """Raised when Jinja2 rendering fails."""


class EmailService:
    """Orchestrates template lookup, rendering, and delivery.

    Parameters
    ----------
    registry    : EmailSenderRegistry — provides the active transport
    db_session  : SQLAlchemy session — for template queries
    log_sends   : if True, persist a send log record (Sprint 05 extension)
    """

    def __init__(
        self,
        registry: EmailSenderRegistry,
        db_session,
        log_sends: bool = False,
    ) -> None:
        self._registry = registry
        self._session = db_session
        self._log_sends = log_sends
        self._jinja = Environment(loader=BaseLoader(), autoescape=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_event(
        self,
        event_type: str,
        to_address: str,
        context: dict,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
    ) -> bool:
        """Look up the template for *event_type*, render, and send.

        Returns True if sent, False if template is inactive or not found.
        Raises EmailSendError / TemplateRenderError on hard failures.
        """
        template = self._get_template(event_type)
        if template is None or not template.is_active:
            return False

        subject = self._render(template.subject, context)
        html_body = self._render(template.html_body, context)
        text_body = (
            self._render(template.text_body, context) if template.text_body else ""
        )

        message = EmailMessage(
            to_address=to_address,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            from_address=from_address or "",
            from_name=from_name or "",
        )
        self._registry.active().send(message)
        return True

    def render_preview(self, event_type: str, context: dict) -> dict:
        """Render subject + html_body for admin preview (no delivery)."""
        template = self._get_template(event_type)
        if template is None:
            return {"subject": "", "html_body": "", "text_body": ""}
        return {
            "subject": self._render(template.subject, context),
            "html_body": self._render(template.html_body, context),
            "text_body": self._render(template.text_body, context)
            if template.text_body
            else "",
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_template(self, event_type: str):
        from plugins.email.src.models.email_template import EmailTemplate

        return (
            self._session.query(EmailTemplate).filter_by(event_type=event_type).first()
        )

    def _render(self, source: str, context: dict) -> str:
        try:
            tmpl = self._jinja.from_string(source)
            return tmpl.render(**context)
        except TemplateSyntaxError as exc:
            raise TemplateRenderError(f"Jinja2 syntax error: {exc}") from exc
        except Exception as exc:
            raise TemplateRenderError(f"Template render failed: {exc}") from exc
