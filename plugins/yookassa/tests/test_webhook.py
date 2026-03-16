"""Tests for YooKassa webhook event-driven verification."""
import hashlib
import hmac as hmac_mod
import json
import pytest
from uuid import uuid4, UUID
from unittest.mock import MagicMock

from flask import Flask

from src.plugins.config_store import PluginConfigEntry
from src.events.payment_events import PaymentCapturedEvent


@pytest.fixture
def mock_container(mocker):
    """Mock DI container."""
    container = mocker.MagicMock()
    container.invoice_repository.return_value = mocker.MagicMock()
    container.subscription_repository.return_value = mocker.MagicMock()
    container.event_dispatcher.return_value = mocker.MagicMock()
    return container


@pytest.fixture
def app(mock_yookassa_api, mock_config_store, mock_container, mocker):
    """Flask app with YooKassa blueprint."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True

    mocker.patch("src.middleware.auth.AuthService", MagicMock())
    mocker.patch("src.middleware.auth.UserRepository", MagicMock())
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


class TestWebhookEventEmission:
    """Verify that webhook handlers emit correct domain events."""

    def test_emits_payment_captured_event(
        self, client, mock_container, yookassa_config
    ):
        """payment.succeeded should emit PaymentCapturedEvent."""
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
                "id": "pay_evt_1",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "500.00", "currency": "RUB"},
                "payment_method": {"id": "pm_1", "saved": False},
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

    def test_event_correct_invoice_id(self, client, mock_container, yookassa_config):
        """Emitted event should have correct invoice_id."""
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
                "id": "pay_evt_2",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "250.00", "currency": "RUB"},
                "payment_method": {"id": "pm_2", "saved": False},
            },
        }
        _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )

        event = mock_container.event_dispatcher.return_value.emit.call_args[0][0]
        assert str(event.invoice_id) == invoice_id

    def test_event_correct_amount(self, client, mock_container, yookassa_config):
        """Emitted event should have correct amount."""
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
                "id": "pay_evt_3",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "999.95", "currency": "RUB"},
                "payment_method": {"id": "pm_3", "saved": False},
            },
        }
        _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )

        event = mock_container.event_dispatcher.return_value.emit.call_args[0][0]
        assert event.amount == "999.95"

    def test_event_correct_provider(self, client, mock_container, yookassa_config):
        """Emitted event should have provider='yookassa'."""
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
                "id": "pay_evt_4",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "100.00", "currency": "RUB"},
                "payment_method": {"id": "pm_4", "saved": False},
            },
        }
        _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )

        event = mock_container.event_dispatcher.return_value.emit.call_args[0][0]
        assert event.provider == "yookassa"

    def test_event_correct_transaction_id(
        self, client, mock_container, yookassa_config
    ):
        """Emitted event should have correct transaction_id (payment_id)."""
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
                "id": "pay_tx_99",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "50.00", "currency": "RUB"},
                "payment_method": {"id": "pm_5", "saved": False},
            },
        }
        _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )

        event = mock_container.event_dispatcher.return_value.emit.call_args[0][0]
        assert event.transaction_id == "pay_tx_99"

    def test_webhook_no_direct_domain_mutations(
        self, client, mock_container, yookassa_config
    ):
        """Webhook handlers should NOT call save on repositories directly."""
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
                "id": "pay_nosave",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "100.00", "currency": "RUB"},
                "payment_method": {"id": "pm_6", "saved": False},
            },
        }
        _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )

        # No direct saves on invoice or subscription repos
        mock_container.invoice_repository.return_value.save.assert_not_called()
        mock_container.subscription_repository.return_value.save.assert_not_called()


class TestPaymentCanceled:
    """Tests for payment.canceled webhook handler (marks invoice FAILED, emits event)."""

    def _setup_invoice_with_subscription(self, mock_container, invoice_id, sub_id):
        """Helper to configure invoice + subscription line item in mock_container."""
        mock_invoice = MagicMock()
        mock_invoice.id = UUID(invoice_id)
        mock_invoice.status = MagicMock()

        mock_li = MagicMock()
        from src.models.enums import LineItemType

        mock_li.item_type = LineItemType.SUBSCRIPTION
        mock_li.item_id = sub_id
        mock_invoice.line_items = [mock_li]

        mock_container.invoice_repository.return_value.find_by_id.return_value = (
            mock_invoice
        )

        mock_subscription = MagicMock()
        mock_subscription.id = sub_id
        mock_subscription.user_id = uuid4()
        mock_container.subscription_repository.return_value.find_by_id.return_value = (
            mock_subscription
        )

        return mock_invoice, mock_subscription

    def test_payment_canceled_marks_invoice_failed(
        self, client, mock_container, yookassa_config
    ):
        """payment.canceled should mark invoice status as FAILED and call save."""
        from src.models.enums import InvoiceStatus

        invoice_id = str(uuid4())
        sub_id = uuid4()
        mock_invoice, _ = self._setup_invoice_with_subscription(
            mock_container, invoice_id, sub_id
        )

        event_payload = {
            "event": "payment.canceled",
            "object": {
                "id": "pay_canceled_1",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "100.00", "currency": "RUB"},
            },
        }
        resp = _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )
        assert resp.status_code == 200

        assert mock_invoice.status == InvoiceStatus.FAILED
        mock_container.invoice_repository.return_value.save.assert_called_once_with(
            mock_invoice
        )

    def test_payment_canceled_emits_payment_failed_event(
        self, client, mock_container, yookassa_config
    ):
        """payment.canceled should emit PaymentFailedEvent with correct subscription_id."""
        from src.events.payment_events import PaymentFailedEvent

        invoice_id = str(uuid4())
        sub_id = uuid4()
        _, mock_subscription = self._setup_invoice_with_subscription(
            mock_container, invoice_id, sub_id
        )

        event_payload = {
            "event": "payment.canceled",
            "object": {
                "id": "pay_canceled_2",
                "metadata": {"invoice_id": invoice_id},
                "amount": {"value": "100.00", "currency": "RUB"},
            },
        }
        resp = _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )
        assert resp.status_code == 200

        emit_call = mock_container.event_dispatcher.return_value.emit
        emit_call.assert_called_once()
        event = emit_call.call_args[0][0]
        assert isinstance(event, PaymentFailedEvent)
        assert event.subscription_id == mock_subscription.id

    def test_payment_canceled_unknown_invoice_no_op(
        self, client, mock_container, yookassa_config
    ):
        """payment.canceled with unknown invoice_id should be a no-op (no save, no emit)."""
        mock_container.invoice_repository.return_value.find_by_id.return_value = None

        event_payload = {
            "event": "payment.canceled",
            "object": {
                "id": "pay_canceled_unk",
                "metadata": {"invoice_id": str(uuid4())},
                "amount": {"value": "100.00", "currency": "RUB"},
            },
        }
        resp = _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )
        assert resp.status_code == 200

        mock_container.invoice_repository.return_value.save.assert_not_called()
        mock_container.event_dispatcher.return_value.emit.assert_not_called()

    def test_payment_canceled_no_invoice_id_no_op(
        self, client, mock_container, yookassa_config
    ):
        """payment.canceled with no invoice_id in metadata should be a no-op."""
        event_payload = {
            "event": "payment.canceled",
            "object": {
                "id": "pay_canceled_nometa",
                "metadata": {},
                "amount": {"value": "100.00", "currency": "RUB"},
            },
        }
        resp = _make_webhook_call(
            client, event_payload, yookassa_config["test_webhook_secret"]
        )
        assert resp.status_code == 200

        mock_container.invoice_repository.return_value.save.assert_not_called()
        mock_container.event_dispatcher.return_value.emit.assert_not_called()
