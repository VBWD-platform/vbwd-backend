"""S13 — split handler contract tests.

Each sub-handler accepts exactly one event type. ``can_handle`` is the
only place isinstance-on-event lives.
"""
from unittest.mock import MagicMock

from vbwd.events.security_events import (
    PasswordResetExecuteEvent,
    PasswordResetRequestEvent,
)
from vbwd.handlers.password_reset_handler import (
    PasswordResetExecuteHandler,
    PasswordResetRequestHandler,
)


def _stub_service(token: str | None = "tok123", success: bool = True):
    service = MagicMock()
    service.create_reset_token.return_value = MagicMock(
        success=success,
        token=token,
        email="user@example.com",
        user_id="user-1",
    )
    service.reset_password.return_value = MagicMock(
        success=success,
        email="user@example.com",
        user_id="user-1",
        failure_reason=None if success else "bad_token",
        error=None if success else "Invalid token",
    )
    return service


def test_request_handler_accepts_only_request_event():
    handler = PasswordResetRequestHandler(_stub_service(), MagicMock(), MagicMock())
    assert handler.can_handle(
        PasswordResetRequestEvent(email="u@x.io", request_ip="1.1.1.1")
    )
    assert not handler.can_handle(
        PasswordResetExecuteEvent(
            token="t", new_password="P@ss123!", reset_ip="2.2.2.2"
        )
    )


def test_execute_handler_accepts_only_execute_event():
    handler = PasswordResetExecuteHandler(_stub_service(), MagicMock(), MagicMock())
    assert handler.can_handle(
        PasswordResetExecuteEvent(
            token="t", new_password="P@ss123!", reset_ip="2.2.2.2"
        )
    )
    assert not handler.can_handle(
        PasswordResetRequestEvent(email="u@x.io", request_ip="1.1.1.1")
    )


def test_request_handler_returns_success_when_email_unknown():
    """No-leak: success result even when service reports no token."""
    service = _stub_service(token=None)
    handler = PasswordResetRequestHandler(service, MagicMock(), MagicMock())
    result = handler.handle(
        PasswordResetRequestEvent(email="unknown@example.com", request_ip="9.9.9.9")
    )
    assert result.success is True


def test_execute_handler_logs_failure_on_bad_token():
    service = _stub_service(success=False)
    activity_logger = MagicMock()
    handler = PasswordResetExecuteHandler(service, MagicMock(), activity_logger)
    result = handler.handle(
        PasswordResetExecuteEvent(
            token="invalid-token", new_password="P@ss123!", reset_ip="2.2.2.2"
        )
    )
    assert result.success is False
    activity_logger.log.assert_called_once()
    call_kwargs = activity_logger.log.call_args.kwargs
    assert call_kwargs["action"] == "password_reset_failed"


def test_no_isinstance_chain_in_request_handler_handle():
    """``handle()`` body has at most one isinstance check (the type guard)."""
    import inspect

    source = inspect.getsource(PasswordResetRequestHandler.handle)
    assert source.count("isinstance") <= 1


def test_no_isinstance_chain_in_execute_handler_handle():
    import inspect

    source = inspect.getsource(PasswordResetExecuteHandler.handle)
    assert source.count("isinstance") <= 1
