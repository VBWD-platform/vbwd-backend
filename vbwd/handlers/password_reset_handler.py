"""Password reset event handlers (S13 — SRP/OCP split).

Two single-purpose handlers, one per event type. Adding a future
``PasswordResetConfirmedEvent`` becomes additive (a third handler
class) rather than a modification to ``handle()`` (OCP win).
"""
from vbwd.events.domain import DomainEvent, EventResult, IEventHandler
from vbwd.events.security_events import (
    PasswordResetExecuteEvent,
    PasswordResetRequestEvent,
)
from vbwd.services.email_service import EmailService
from vbwd.services.password_reset_service import PasswordResetService


class PasswordResetRequestHandler(IEventHandler):
    """Handles ``security.password_reset.request`` events.

    Flow: route emits event → this handler → service creates token →
    email sent if user exists → activity logged. Always returns success
    (don't reveal whether the email is registered).
    """

    def __init__(
        self,
        password_reset_service: PasswordResetService,
        email_service: EmailService,
        activity_logger,
        reset_url_base: str = "https://app.example.com/reset-password",
    ) -> None:
        self._reset_service = password_reset_service
        self._email_service = email_service
        self._activity_logger = activity_logger
        self._reset_url_base = reset_url_base

    def can_handle(self, event: DomainEvent) -> bool:
        return isinstance(event, PasswordResetRequestEvent)

    def handle(self, event: DomainEvent) -> EventResult:
        # narrowed by can_handle, but keep the type guard for safety
        if not isinstance(event, PasswordResetRequestEvent):
            return EventResult.error_result("Unexpected event type")
        return self._do(event)

    def _do(self, event: PasswordResetRequestEvent) -> EventResult:
        result = self._reset_service.create_reset_token(event.email)

        if result.success and result.token:
            reset_url = f"{self._reset_url_base}?token={result.token}"
            self._email_service.send_template(
                to=result.email or "",
                template="password_reset",
                context={"reset_url": reset_url, "expires_in": "1 hour"},
            )
            self._activity_logger.log(
                action="password_reset_requested",
                user_id=result.user_id,
                metadata={"ip": event.request_ip},
            )

        # Always success to not reveal email existence.
        return EventResult.success_result(
            {"message": "If email exists, reset link sent"}
        )


class PasswordResetExecuteHandler(IEventHandler):
    """Handles ``security.password_reset.execute`` events.

    Flow: route emits event → this handler → service resets password →
    confirmation email + success log, OR failure log + error result.
    """

    def __init__(
        self,
        password_reset_service: PasswordResetService,
        email_service: EmailService,
        activity_logger,
    ) -> None:
        self._reset_service = password_reset_service
        self._email_service = email_service
        self._activity_logger = activity_logger

    def can_handle(self, event: DomainEvent) -> bool:
        return isinstance(event, PasswordResetExecuteEvent)

    def handle(self, event: DomainEvent) -> EventResult:
        if not isinstance(event, PasswordResetExecuteEvent):
            return EventResult.error_result("Unexpected event type")
        return self._do(event)

    def _do(self, event: PasswordResetExecuteEvent) -> EventResult:
        result = self._reset_service.reset_password(event.token, event.new_password)

        if result.success:
            self._email_service.send_template(
                to=result.email or "", template="password_changed", context={}
            )
            self._activity_logger.log(
                action="password_reset_completed",
                user_id=result.user_id,
                metadata={"ip": event.reset_ip},
            )
            return EventResult.success_result({"message": "Password reset successful"})

        # Log failed attempt.
        self._activity_logger.log(
            action="password_reset_failed",
            metadata={
                "reason": result.failure_reason,
                "ip": event.reset_ip,
                "token_prefix": (
                    event.token[:8] + "..." if len(event.token) > 8 else event.token
                ),
            },
        )
        return EventResult.error_result(
            error=result.error or "Unknown error",
            error_type=result.failure_reason or "unknown",
        )


# Backward-compat shim: tests and callers that imported ``PasswordResetHandler``
# get a class that dispatches to whichever sub-handler matches. New code
# should register the two sub-handlers directly. Removed after the next
# transitive caller sweep.
class PasswordResetHandler(IEventHandler):
    """Legacy combined handler — delegates to the split sub-handlers (S13)."""

    def __init__(
        self,
        password_reset_service: PasswordResetService,
        email_service: EmailService,
        activity_logger,
        reset_url_base: str = "https://app.example.com/reset-password",
    ) -> None:
        self._request_handler = PasswordResetRequestHandler(
            password_reset_service,
            email_service,
            activity_logger,
            reset_url_base,
        )
        self._execute_handler = PasswordResetExecuteHandler(
            password_reset_service, email_service, activity_logger
        )

    def can_handle(self, event: DomainEvent) -> bool:
        return self._request_handler.can_handle(
            event
        ) or self._execute_handler.can_handle(event)

    def handle(self, event: DomainEvent) -> EventResult:
        if self._request_handler.can_handle(event):
            return self._request_handler.handle(event)
        if self._execute_handler.can_handle(event):
            return self._execute_handler.handle(event)
        return EventResult.error_result("Unknown event type")

    # Expose the original method names so existing tests keep working.
    def handle_reset_request(self, event: PasswordResetRequestEvent) -> EventResult:
        return self._request_handler._do(event)

    def handle_reset_execute(self, event: PasswordResetExecuteEvent) -> EventResult:
        return self._execute_handler._do(event)
