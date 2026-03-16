"""Unit tests — EmailPlugin wires event handlers via EventBus."""
import pytest
from unittest.mock import MagicMock, patch

from src.events.bus import EventBus
from plugins.email import EmailPlugin


def _enabled_plugin(config=None) -> tuple:
    """Return (plugin, bus) with plugin initialized + enabled."""
    plugin = EmailPlugin()
    plugin.initialize(config or {})
    plugin.enable()
    bus = EventBus()
    plugin.register_event_handlers(bus)
    return plugin, bus


class TestEmailPluginRegistersHandlers:
    def test_subscription_activated_has_subscriber(self):
        _plugin, bus = _enabled_plugin()
        assert bus.has_subscribers("subscription.activated")

    def test_subscription_cancelled_has_subscriber(self):
        _plugin, bus = _enabled_plugin()
        assert bus.has_subscribers("subscription.cancelled")

    def test_subscription_payment_failed_has_subscriber(self):
        _plugin, bus = _enabled_plugin()
        assert bus.has_subscribers("subscription.payment_failed")

    def test_subscription_renewed_has_subscriber(self):
        _plugin, bus = _enabled_plugin()
        assert bus.has_subscribers("subscription.renewed")

    def test_user_registered_has_subscriber(self):
        _plugin, bus = _enabled_plugin()
        assert bus.has_subscribers("user.registered")

    def test_user_password_reset_has_subscriber(self):
        _plugin, bus = _enabled_plugin()
        assert bus.has_subscribers("user.password_reset")


class TestEmailHandlersFire:
    def test_subscription_activated_calls_send_event(self):
        """Publishing subscription.activated triggers EmailService.send_event."""
        _plugin, bus = _enabled_plugin({"smtp_host": "localhost"})

        mock_svc = MagicMock()
        mock_svc.send_event.return_value = True

        with patch(
            "plugins.email.src.handlers._make_email_service", return_value=mock_svc
        ):
            bus.publish(
                "subscription.activated",
                {
                    "user_email": "user@example.com",
                    "user_name": "Alice",
                    "plan_name": "Pro",
                    "plan_price": "$29",
                    "billing_period": "monthly",
                    "start_date": "2026-03-15",
                    "next_billing_date": "2026-04-15",
                    "dashboard_url": "/dashboard",
                },
            )

        mock_svc.send_event.assert_called_once()
        args = mock_svc.send_event.call_args
        assert args[0][0] == "subscription.activated"
        assert args[0][1] == "user@example.com"

    def test_user_registered_calls_send_event(self):
        _plugin, bus = _enabled_plugin()
        mock_svc = MagicMock()
        mock_svc.send_event.return_value = True

        with patch(
            "plugins.email.src.handlers._make_email_service", return_value=mock_svc
        ):
            bus.publish(
                "user.registered",
                {
                    "user_email": "new@example.com",
                    "user_name": "Bob",
                    "login_url": "/login",
                },
            )

        mock_svc.send_event.assert_called_once()
        assert mock_svc.send_event.call_args[0][1] == "new@example.com"

    def test_send_failure_does_not_propagate(self):
        """A crashing EmailService doesn't raise to the caller."""
        _plugin, bus = _enabled_plugin()
        mock_svc = MagicMock()
        mock_svc.send_event.side_effect = RuntimeError("smtp down")

        with patch(
            "plugins.email.src.handlers._make_email_service", return_value=mock_svc
        ):
            # Should not raise
            bus.publish("user.registered", {"user_email": "a@b.com"})


class TestRegisterHandlersFunctionDirectly:
    def test_register_handlers_subscribes_all_events(self):
        from plugins.email.src.handlers import register_handlers

        bus = EventBus()
        register_handlers(bus, {})

        for event in [
            "subscription.activated",
            "subscription.cancelled",
            "subscription.payment_failed",
            "subscription.renewed",
            "user.registered",
            "user.password_reset",
        ]:
            assert bus.has_subscribers(event), f"Expected subscriber for {event}"
