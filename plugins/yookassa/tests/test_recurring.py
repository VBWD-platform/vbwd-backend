"""Tests for YooKassa recurring billing flows."""
import hashlib
import hmac as hmac_mod
import json
import pytest
from decimal import Decimal
from uuid import uuid4, UUID
from unittest.mock import MagicMock

from flask import Flask

from src.plugins.config_store import PluginConfigEntry
from src.models.enums import InvoiceStatus, LineItemType
from src.events.payment_events import PaymentCapturedEvent


@pytest.fixture
def mock_container(mocker):
    """Mock DI container."""
    container = mocker.MagicMock()
    container.invoice_repository.return_value = mocker.MagicMock()
    container.subscription_repository.return_value = mocker.MagicMock()
    container.user_repository.return_value = mocker.MagicMock()
    container.event_dispatcher.return_value = mocker.MagicMock()
    return container


@pytest.fixture
def app(mock_yookassa_api, mock_config_store, mock_container, mocker):
    """Flask app with YooKassa blueprint."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True

    user_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    mock_auth_service = MagicMock()
    mock_auth_service.return_value.verify_token.return_value = str(user_id)
    mocker.patch("src.middleware.auth.AuthService", mock_auth_service)

    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.status.value = "ACTIVE"
    mock_user_repo = MagicMock()
    mock_user_repo.return_value.find_by_id.return_value = mock_user
    mocker.patch("src.middleware.auth.UserRepository", mock_user_repo)
    mocker.patch("src.middleware.auth.db", MagicMock())

    from plugins.yookassa.routes import yookassa_plugin_bp

    flask_app.register_blueprint(
        yookassa_plugin_bp, url_prefix="/api/v1/plugins/yookassa"
    )
    flask_app.config_store = mock_config_store
    flask_app.container = mock_container
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test_token_123"}


def _make_webhook_call(client, event_payload, webhook_secret):
    """Helper to make a verified webhook call."""
    payload_bytes = json.dumps(event_payload).encode()
    sig = hmac_mod.new(
        webhook_secret.encode(), payload_bytes, hashlib.sha256
    ).hexdigest()

    return client.post(
        "/api/v1/plugins/yookassa/webhook",
        data=payload_bytes,
        headers={"X-YooKassa-Signature": sig},
        content_type="application/json",
    )


class TestDetermineSessionMode:
    """Test determine_session_mode via shared helpers."""

    def test_determine_mode_one_time(self, app):
        """Should return 'payment' for non-recurring invoice."""
        with app.app_context():
            from src.plugins.payment_route_helpers import determine_session_mode

            invoice = MagicMock()
            invoice.line_items = []
            assert determine_session_mode(invoice) == "payment"


class TestRecurringPaymentSavesMethod:
    """Test that payment.succeeded with saved method stores payment_method_id."""

    def test_saves_payment_method_on_subscription(
        self, client, mock_container, yookassa_config
    ):
        """Should store payment_method_id on Subscription when method is saved."""
        invoice_id = str(uuid4())
        sub_id = uuid4()

        mock_invoice = MagicMock()
        mock_invoice.id = UUID(invoice_id)
        mock_invoice.status.value = "PENDING"
        mock_li = MagicMock()
        mock_li.item_type = LineItemType.SUBSCRIPTION
        mock_li.item_id = sub_id
        mock_invoice.line_items = [mock_li]
        mock_container.invoice_repository.return_value.find_by_id.return_value = (
            mock_invoice
        )

        mock_subscription = MagicMock()
        mock_subscription.id = sub_id
        mock_container.subscription_repository.return_value.find_by_id.return_value = (
            mock_subscription
        )

        event_payload = {
            "event": "payment.succeeded",
            "object": {
                "id": "pay_rec_1",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "99.99", "currency": "RUB"},
                "payment_method": {"id": "pm_saved_123", "saved": True},
            },
        }
        resp = _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )
        assert resp.status_code == 200

        # Verify payment_method_id was stored
        assert mock_subscription.provider_subscription_id == "pm_saved_123"
        mock_container.subscription_repository.return_value.save.assert_called_once()

    def test_no_save_when_method_not_saved(
        self, client, mock_container, yookassa_config
    ):
        """Should NOT store payment_method_id when saved=False."""
        invoice_id = str(uuid4())

        mock_invoice = MagicMock()
        mock_invoice.id = UUID(invoice_id)
        mock_invoice.status.value = "PENDING"
        mock_invoice.line_items = []
        mock_container.invoice_repository.return_value.find_by_id.return_value = (
            mock_invoice
        )

        event_payload = {
            "event": "payment.succeeded",
            "object": {
                "id": "pay_rec_2",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "50.00", "currency": "RUB"},
                "payment_method": {"id": "pm_not_saved", "saved": False},
            },
        }
        resp = _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )
        assert resp.status_code == 200

        # No subscription save should have been called
        mock_container.subscription_repository.return_value.save.assert_not_called()


class TestRecurringPaymentEmitsEvent:
    """Test that recurring payment.succeeded emits PaymentCapturedEvent."""

    def test_emits_event_for_recurring_payment(
        self, client, mock_container, yookassa_config
    ):
        """payment.succeeded with saved method should emit PaymentCapturedEvent."""
        invoice_id = str(uuid4())
        sub_id = uuid4()

        mock_invoice = MagicMock()
        mock_invoice.id = UUID(invoice_id)
        mock_invoice.status.value = "PENDING"
        mock_li = MagicMock()
        mock_li.item_type = LineItemType.SUBSCRIPTION
        mock_li.item_id = sub_id
        mock_invoice.line_items = [mock_li]
        mock_container.invoice_repository.return_value.find_by_id.return_value = (
            mock_invoice
        )

        mock_subscription = MagicMock()
        mock_subscription.id = sub_id
        mock_container.subscription_repository.return_value.find_by_id.return_value = (
            mock_subscription
        )

        event_payload = {
            "event": "payment.succeeded",
            "object": {
                "id": "pay_rec_emit",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "199.00", "currency": "RUB"},
                "payment_method": {"id": "pm_rec_emit", "saved": True},
            },
        }
        resp = _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )
        assert resp.status_code == 200

        emit_call = mock_container.event_dispatcher.return_value.emit
        emit_call.assert_called_once()
        event = emit_call.call_args[0][0]
        assert isinstance(event, PaymentCapturedEvent)
        assert event.provider == "yookassa"
        assert str(event.invoice_id) == invoice_id


class TestPaymentCanceledWebhook:
    """Test payment.canceled webhook handling."""

    def test_webhook_payment_canceled(self, client, mock_container, yookassa_config):
        """Should return 200 for payment.canceled (warning logged, no event)."""
        invoice_id = str(uuid4())

        event_payload = {
            "event": "payment.canceled",
            "object": {
                "id": "pay_cancel_1",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "100.00", "currency": "RUB"},
            },
        }
        resp = _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )
        assert resp.status_code == 200

        # No event emitted for cancelation (just logs)
        mock_container.event_dispatcher.return_value.emit.assert_not_called()


class TestRefundSucceededWebhook:
    """Test refund.succeeded webhook handling."""

    def test_webhook_refund_succeeded(self, client, mock_container, yookassa_config):
        """Should return 200 for refund.succeeded (logged, no domain event)."""
        event_payload = {
            "event": "refund.succeeded",
            "object": {
                "id": "ref_wh_1",
                "payment_id": "pay_ref_1",
                "amount": {"value": "50.00", "currency": "RUB"},
            },
        }
        resp = _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )
        assert resp.status_code == 200

        # Refund event just logs, no domain event emitted
        mock_container.event_dispatcher.return_value.emit.assert_not_called()
