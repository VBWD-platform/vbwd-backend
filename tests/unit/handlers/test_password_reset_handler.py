"""Tests for PasswordResetHandler - TDD First."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4


class TestPasswordResetHandler:
    """Test suite for PasswordResetHandler."""

    @pytest.fixture
    def mock_password_reset_service(self):
        """Create mock password reset service."""
        return Mock()

    @pytest.fixture
    def mock_email_service(self):
        """Create mock email service."""
        return Mock()

    @pytest.fixture
    def mock_activity_logger(self):
        """Create mock activity logger."""
        return Mock()

    @pytest.fixture
    def handler(
        self, mock_password_reset_service, mock_email_service, mock_activity_logger
    ):
        """Create PasswordResetHandler with mocked dependencies."""
        from vbwd.handlers.password_reset_handler import PasswordResetHandler

        return PasswordResetHandler(
            password_reset_service=mock_password_reset_service,
            email_service=mock_email_service,
            activity_logger=mock_activity_logger,
            reset_url_base="https://app.example.com/reset-password",
        )

    # --- Tests for handle_reset_request ---

    def test_handle_reset_request_calls_service(
        self, handler, mock_password_reset_service
    ):
        """Handler calls service to create reset token."""
        # Arrange
        from vbwd.events.security_events import PasswordResetRequestEvent
        from vbwd.services.password_reset_service import ResetRequestResult

        mock_password_reset_service.create_reset_token.return_value = (
            ResetRequestResult(
                success=True,
                user_id=str(uuid4()),
                email="test@example.com",
                token="test_token_123",
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
        )

        event = PasswordResetRequestEvent(
            email="test@example.com", request_ip="127.0.0.1"
        )

        # Act
        result = handler.handle_reset_request(event)

        # Assert
        mock_password_reset_service.create_reset_token.assert_called_once_with(
            "test@example.com"
        )
        assert result.success is True

    def test_handle_reset_request_sends_email_when_user_exists(
        self, handler, mock_password_reset_service, mock_email_service
    ):
        """Email sent when user exists and token created."""
        # Arrange
        from vbwd.events.security_events import PasswordResetRequestEvent
        from vbwd.services.password_reset_service import ResetRequestResult

        mock_password_reset_service.create_reset_token.return_value = (
            ResetRequestResult(
                success=True,
                user_id=str(uuid4()),
                email="test@example.com",
                token="test_token_123",
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
        )

        event = PasswordResetRequestEvent(
            email="test@example.com", request_ip="127.0.0.1"
        )

        # Act
        handler.handle_reset_request(event)

        # Assert
        mock_email_service.send_template.assert_called_once()
        call_args = mock_email_service.send_template.call_args
        assert call_args.kwargs["to"] == "test@example.com"
        assert call_args.kwargs["template"] == "password_reset"
        assert "reset_url" in call_args.kwargs["context"]
        assert "test_token_123" in call_args.kwargs["context"]["reset_url"]

    def test_handle_reset_request_no_email_when_user_not_found(
        self, handler, mock_password_reset_service, mock_email_service
    ):
        """No email sent when user doesn't exist."""
        # Arrange
        from vbwd.events.security_events import PasswordResetRequestEvent
        from vbwd.services.password_reset_service import ResetRequestResult

        mock_password_reset_service.create_reset_token.return_value = ResetRequestResult(
            success=True,
            # No token or user_id - user not found
        )

        event = PasswordResetRequestEvent(
            email="unknown@example.com", request_ip="127.0.0.1"
        )

        # Act
        result = handler.handle_reset_request(event)

        # Assert - should still succeed but no email sent
        assert result.success is True
        mock_email_service.send_template.assert_not_called()

    def test_handle_reset_request_logs_activity(
        self, handler, mock_password_reset_service, mock_activity_logger
    ):
        """Activity logged when reset requested."""
        # Arrange
        from vbwd.events.security_events import PasswordResetRequestEvent
        from vbwd.services.password_reset_service import ResetRequestResult

        user_id = str(uuid4())
        mock_password_reset_service.create_reset_token.return_value = (
            ResetRequestResult(
                success=True,
                user_id=user_id,
                email="test@example.com",
                token="test_token_123",
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
        )

        event = PasswordResetRequestEvent(
            email="test@example.com", request_ip="192.168.1.1"
        )

        # Act
        handler.handle_reset_request(event)

        # Assert
        mock_activity_logger.log.assert_called_once()
        call_args = mock_activity_logger.log.call_args
        assert call_args.kwargs["action"] == "password_reset_requested"
        assert call_args.kwargs["user_id"] == user_id
        assert call_args.kwargs["metadata"]["ip"] == "192.168.1.1"

    def test_handle_reset_request_always_returns_success(
        self, handler, mock_password_reset_service
    ):
        """Always return success to not reveal if email exists."""
        # Arrange
        from vbwd.events.security_events import PasswordResetRequestEvent
        from vbwd.services.password_reset_service import ResetRequestResult

        mock_password_reset_service.create_reset_token.return_value = (
            ResetRequestResult(success=True)
        )  # User not found but still success

        event = PasswordResetRequestEvent(
            email="unknown@example.com", request_ip="127.0.0.1"
        )

        # Act
        result = handler.handle_reset_request(event)

        # Assert
        assert result.success is True

    # --- Tests for handle_reset_execute ---

    def test_handle_reset_execute_calls_service(
        self, handler, mock_password_reset_service
    ):
        """Handler calls service to reset password."""
        # Arrange
        from vbwd.events.security_events import PasswordResetExecuteEvent
        from vbwd.services.password_reset_service import ResetResult

        mock_password_reset_service.reset_password.return_value = ResetResult(
            success=True, user_id=str(uuid4()), email="test@example.com"
        )

        event = PasswordResetExecuteEvent(
            token="valid_token", new_password="NewPassword123!", reset_ip="127.0.0.1"
        )

        # Act
        result = handler.handle_reset_execute(event)

        # Assert
        mock_password_reset_service.reset_password.assert_called_once_with(
            "valid_token", "NewPassword123!"
        )
        assert result.success is True

    def test_handle_reset_execute_sends_confirmation_email(
        self, handler, mock_password_reset_service, mock_email_service
    ):
        """Confirmation email sent on successful reset."""
        # Arrange
        from vbwd.events.security_events import PasswordResetExecuteEvent
        from vbwd.services.password_reset_service import ResetResult

        mock_password_reset_service.reset_password.return_value = ResetResult(
            success=True, user_id=str(uuid4()), email="test@example.com"
        )

        event = PasswordResetExecuteEvent(
            token="valid_token", new_password="NewPassword123!", reset_ip="127.0.0.1"
        )

        # Act
        handler.handle_reset_execute(event)

        # Assert
        mock_email_service.send_template.assert_called_once()
        call_args = mock_email_service.send_template.call_args
        assert call_args.kwargs["to"] == "test@example.com"
        assert call_args.kwargs["template"] == "password_changed"

    def test_handle_reset_execute_logs_success(
        self, handler, mock_password_reset_service, mock_activity_logger
    ):
        """Activity logged on successful reset."""
        # Arrange
        from vbwd.events.security_events import PasswordResetExecuteEvent
        from vbwd.services.password_reset_service import ResetResult

        user_id = str(uuid4())
        mock_password_reset_service.reset_password.return_value = ResetResult(
            success=True, user_id=user_id, email="test@example.com"
        )

        event = PasswordResetExecuteEvent(
            token="valid_token", new_password="NewPassword123!", reset_ip="192.168.1.1"
        )

        # Act
        handler.handle_reset_execute(event)

        # Assert
        mock_activity_logger.log.assert_called_once()
        call_args = mock_activity_logger.log.call_args
        assert call_args.kwargs["action"] == "password_reset_completed"
        assert call_args.kwargs["user_id"] == user_id

    def test_handle_reset_execute_returns_error_on_failure(
        self, handler, mock_password_reset_service
    ):
        """Error returned when reset fails."""
        # Arrange
        from vbwd.events.security_events import PasswordResetExecuteEvent
        from vbwd.services.password_reset_service import ResetResult

        mock_password_reset_service.reset_password.return_value = ResetResult(
            success=False, error="Token expired", failure_reason="expired"
        )

        event = PasswordResetExecuteEvent(
            token="expired_token", new_password="NewPassword123!", reset_ip="127.0.0.1"
        )

        # Act
        result = handler.handle_reset_execute(event)

        # Assert
        assert result.success is False
        assert result.error == "Token expired"
        assert result.error_type == "expired"

    def test_handle_reset_execute_logs_failure(
        self, handler, mock_password_reset_service, mock_activity_logger
    ):
        """Failed attempt logged for security monitoring."""
        # Arrange
        from vbwd.events.security_events import PasswordResetExecuteEvent
        from vbwd.services.password_reset_service import ResetResult

        mock_password_reset_service.reset_password.return_value = ResetResult(
            success=False, error="Invalid token", failure_reason="invalid"
        )

        event = PasswordResetExecuteEvent(
            token="invalid_token_12345678",
            new_password="NewPassword123!",
            reset_ip="192.168.1.1",
        )

        # Act
        handler.handle_reset_execute(event)

        # Assert
        mock_activity_logger.log.assert_called_once()
        call_args = mock_activity_logger.log.call_args
        assert call_args.kwargs["action"] == "password_reset_failed"
        assert call_args.kwargs["metadata"]["reason"] == "invalid"
        assert call_args.kwargs["metadata"]["ip"] == "192.168.1.1"

    # --- Tests for can_handle ---

    def test_can_handle_reset_request_event(self, handler):
        """Handler can handle PasswordResetRequestEvent."""
        from vbwd.events.security_events import PasswordResetRequestEvent

        event = PasswordResetRequestEvent(email="test@example.com")
        assert handler.can_handle(event) is True

    def test_can_handle_reset_execute_event(self, handler):
        """Handler can handle PasswordResetExecuteEvent."""
        from vbwd.events.security_events import PasswordResetExecuteEvent

        event = PasswordResetExecuteEvent(token="test", new_password="Test123!")
        assert handler.can_handle(event) is True

    def test_cannot_handle_other_events(self, handler):
        """Handler cannot handle other event types."""
        from vbwd.events.domain import DomainEvent

        event = DomainEvent(name="other.event")
        assert handler.can_handle(event) is False
