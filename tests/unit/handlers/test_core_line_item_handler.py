"""Unit tests for CoreLineItemHandler — TOKEN_BUNDLE only (Sprint 04c)."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.events.line_item_registry import LineItemContext
from vbwd.handlers.core_line_item_handler import CoreLineItemHandler
from vbwd.models.enums import LineItemType, PurchaseStatus


@pytest.fixture()
def container():
    mock_container = MagicMock()
    mock_container.token_balance_repository.return_value = MagicMock()
    mock_container.token_transaction_repository.return_value = MagicMock()
    mock_container.token_bundle_purchase_repository.return_value = MagicMock()
    mock_container.token_service.return_value = MagicMock()
    return mock_container


@pytest.fixture()
def handler(container):
    return CoreLineItemHandler(container)


@pytest.fixture()
def context(container):
    invoice = MagicMock()
    invoice.user_id = uuid4()
    return LineItemContext(
        invoice=invoice, user_id=invoice.user_id, container=container
    )


def _make_line_item(item_type, item_id=None):
    line_item = MagicMock()
    line_item.item_type = item_type
    line_item.item_id = item_id or uuid4()
    return line_item


class TestCanHandleLineItem:
    def test_handles_token_bundle(self, handler, context):
        assert (
            handler.can_handle_line_item(
                _make_line_item(LineItemType.TOKEN_BUNDLE), context
            )
            is True
        )

    def test_rejects_subscription(self, handler, context):
        assert (
            handler.can_handle_line_item(
                _make_line_item(LineItemType.SUBSCRIPTION), context
            )
            is False
        )

    def test_rejects_addon(self, handler, context):
        assert (
            handler.can_handle_line_item(_make_line_item(LineItemType.ADD_ON), context)
            is False
        )

    def test_rejects_custom(self, handler, context):
        assert (
            handler.can_handle_line_item(_make_line_item(LineItemType.CUSTOM), context)
            is False
        )


class TestActivateTokenBundle:
    def test_completes_pending_purchase(self, handler, context, container):
        purchase = MagicMock()
        purchase.id = uuid4()
        purchase.status = PurchaseStatus.PENDING
        purchase.token_amount = 500

        container.token_bundle_purchase_repository.return_value.find_by_id.return_value = (
            purchase
        )

        result = handler.activate_line_item(
            _make_line_item(LineItemType.TOKEN_BUNDLE), context
        )

        assert result.success is True
        assert purchase.status == PurchaseStatus.COMPLETED
        assert result.data.get("tokens_credited") == 500
        # S138.0 Inc 3: credited through TokenService, not a direct repo write.
        credit_call = container.token_service.return_value.credit_tokens.call_args
        assert credit_call.kwargs["amount"] == 500


class TestReverseTokenBundle:
    def test_refunds_completed_purchase(self, handler, context, container):
        purchase = MagicMock()
        purchase.id = uuid4()
        purchase.status = PurchaseStatus.COMPLETED
        purchase.token_amount = 200

        container.token_bundle_purchase_repository.return_value.find_by_id.return_value = (
            purchase
        )

        token_service = MagicMock()
        token_service.refund_tokens.return_value = 200
        container.token_service.return_value = token_service

        result = handler.reverse_line_item(
            _make_line_item(LineItemType.TOKEN_BUNDLE), context
        )

        assert result.success is True
        assert purchase.status == PurchaseStatus.REFUNDED


class TestRestoreTokenBundle:
    def test_restores_refunded_purchase(self, handler, context, container):
        purchase = MagicMock()
        purchase.id = uuid4()
        purchase.status = PurchaseStatus.REFUNDED
        purchase.token_amount = 300

        container.token_bundle_purchase_repository.return_value.find_by_id.return_value = (
            purchase
        )

        result = handler.restore_line_item(
            _make_line_item(LineItemType.TOKEN_BUNDLE), context
        )

        assert result.success is True
        assert purchase.status == PurchaseStatus.COMPLETED
        # S138.0 Inc 3: credited through TokenService, not a direct repo write.
        credit_call = container.token_service.return_value.credit_tokens.call_args
        assert credit_call.kwargs["amount"] == 300
