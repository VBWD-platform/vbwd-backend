"""Tests for email-integrated event handlers.

Subscription/payment email handlers are owned and tested by the
`subscription` plugin (`plugins/subscription/`); the dead core copies and
their tests were removed in Sprint 01 (Phase 0). Only core-owned email
handlers remain here.
"""
from unittest.mock import MagicMock
from uuid import uuid4

from vbwd.events.user_events import UserCreatedEvent
from vbwd.services.email_service import EmailResult


class TestUserCreatedHandlerWithEmail:
    """Tests for UserCreatedHandler with email integration."""

    def test_user_created_sends_welcome_email(self):
        """UserCreatedHandler sends welcome email on user creation."""
        from vbwd.handlers.user_handlers import UserCreatedHandler

        # Mock email service
        mock_email_service = MagicMock()
        mock_email_service.send_welcome_email.return_value = EmailResult(success=True)

        # Create handler with email service
        handler = UserCreatedHandler(email_service=mock_email_service)

        # Create event
        event = UserCreatedEvent(
            user_id=uuid4(), email="newuser@example.com", role="user", first_name="John"
        )

        # Handle event
        result = handler.handle(event)

        # Assert email was sent
        assert result.success is True
        mock_email_service.send_welcome_email.assert_called_once_with(
            to_email="newuser@example.com", first_name="John"
        )

    def test_user_created_handles_email_failure(self):
        """UserCreatedHandler handles email failure gracefully."""
        from vbwd.handlers.user_handlers import UserCreatedHandler

        # Mock email service that fails
        mock_email_service = MagicMock()
        mock_email_service.send_welcome_email.return_value = EmailResult(
            success=False, error="SMTP error"
        )

        handler = UserCreatedHandler(email_service=mock_email_service)

        event = UserCreatedEvent(
            user_id=uuid4(), email="newuser@example.com", role="user"
        )

        # Should still succeed even if email fails
        result = handler.handle(event)

        assert result.success is True
        assert result.data.get("email_sent") is False
