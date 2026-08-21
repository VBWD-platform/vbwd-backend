"""S138.0 Inc 3 — the core TOKEN_BUNDLE paths route through TokenService.

``_activate_token_bundle`` and ``_restore_token_bundle`` used to mutate
``UserTokenBalance`` and append the ``TokenTransaction`` themselves, through the
repositories. That bypassed ``TokenService`` entirely, so no token-movement hook
ever saw a bundle capture or a refund restore — the two paths a bookkeeper most
needs. Routing them through the service also gives them the service's unit of
work (balance + transaction under one commit) for free.

These assert on the seam (the service is called correctly and the repositories
are no longer written to). The proof that a real hook fires on these paths lives
in ``tests/integration/test_token_movement_hook_coverage.py``.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.events.line_item_registry import LineItemContext
from vbwd.handlers.core_line_item_handler import CoreLineItemHandler
from vbwd.models.enums import LineItemType, PurchaseStatus, TokenTransactionType

TOKEN_AMOUNT = 500


@pytest.fixture()
def token_service():
    service = MagicMock()
    service.refund_tokens.return_value = TOKEN_AMOUNT
    return service


@pytest.fixture()
def container(token_service):
    mock_container = MagicMock()
    mock_container.token_service.return_value = token_service
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


def _token_bundle_line_item(item_id):
    line_item = MagicMock()
    line_item.item_type = LineItemType.TOKEN_BUNDLE
    line_item.item_id = item_id
    return line_item


def _purchase(status):
    purchase = MagicMock()
    purchase.id = uuid4()
    purchase.status = status
    purchase.token_amount = TOKEN_AMOUNT
    return purchase


def _register_purchase(container, purchase):
    repo = container.token_bundle_purchase_repository.return_value
    repo.find_by_id.return_value = purchase
    return repo


class TestActivateRoutesThroughTokenService:
    """Bundle capture on invoice payment — previously a direct repo write."""

    def test_credits_through_the_service(
        self, handler, context, container, token_service
    ):
        purchase = _register_purchase(container, _purchase(PurchaseStatus.PENDING))

        result = handler.activate_line_item(
            _token_bundle_line_item(purchase.find_by_id.return_value.id), context
        )

        assert result.success is True
        token_service.credit_tokens.assert_called_once()
        call = token_service.credit_tokens.call_args.kwargs
        assert call["user_id"] == context.user_id
        assert call["amount"] == TOKEN_AMOUNT
        assert call["transaction_type"] == TokenTransactionType.PURCHASE
        assert call["reference_id"] == purchase.find_by_id.return_value.id
        assert call["description"] == f"Token bundle purchase: {TOKEN_AMOUNT} tokens"

    def test_never_writes_the_balance_repository_directly(
        self, handler, context, container
    ):
        _register_purchase(container, _purchase(PurchaseStatus.PENDING))

        handler.activate_line_item(_token_bundle_line_item(uuid4()), context)

        container.token_balance_repository.assert_not_called()
        container.token_transaction_repository.assert_not_called()

    def test_a_non_pending_purchase_still_credits_nothing(
        self, handler, context, container, token_service
    ):
        _register_purchase(container, _purchase(PurchaseStatus.COMPLETED))

        result = handler.activate_line_item(_token_bundle_line_item(uuid4()), context)

        assert result.success is True
        token_service.credit_tokens.assert_not_called()


class TestRestoreRoutesThroughTokenService:
    """Refund reversal — previously a direct repo write."""

    def test_credits_through_the_service(
        self, handler, context, container, token_service
    ):
        purchase = _register_purchase(container, _purchase(PurchaseStatus.REFUNDED))

        result = handler.restore_line_item(
            _token_bundle_line_item(purchase.find_by_id.return_value.id), context
        )

        assert result.success is True
        token_service.credit_tokens.assert_called_once()
        call = token_service.credit_tokens.call_args.kwargs
        assert call["amount"] == TOKEN_AMOUNT
        assert call["transaction_type"] == TokenTransactionType.PURCHASE
        assert call["reference_id"] == purchase.find_by_id.return_value.id
        assert call["description"] == f"Refund reversed: {TOKEN_AMOUNT} tokens restored"

    def test_never_writes_the_balance_repository_directly(
        self, handler, context, container
    ):
        _register_purchase(container, _purchase(PurchaseStatus.REFUNDED))

        handler.restore_line_item(_token_bundle_line_item(uuid4()), context)

        container.token_balance_repository.assert_not_called()
        container.token_transaction_repository.assert_not_called()


class TestReverseAlreadyRoutedThroughTokenService:
    """Regression guard: the refund path already used the service — keep it."""

    def test_refunds_through_the_service(
        self, handler, context, container, token_service
    ):
        _register_purchase(container, _purchase(PurchaseStatus.COMPLETED))

        result = handler.reverse_line_item(_token_bundle_line_item(uuid4()), context)

        assert result.success is True
        assert result.data["tokens_debited"] == TOKEN_AMOUNT
        token_service.refund_tokens.assert_called_once()
