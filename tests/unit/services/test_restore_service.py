"""Tests for RestoreService."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

from vbwd.events.line_item_registry import LineItemHandlerRegistry
from vbwd.handlers.core_line_item_handler import CoreLineItemHandler

try:
    from plugins.subscription.subscription.handlers.line_item_handler import (
        SubscriptionLineItemHandler,
    )
except ImportError:
    pytest.skip("Subscription plugin not installed", allow_module_level=True)
from vbwd.models.enums import (
    InvoiceStatus,
    LineItemType,
    SubscriptionStatus,
    PurchaseStatus,
)


def _make_line_item(item_type, item_id=None):
    """Create a mock line item."""
    line_item = MagicMock()
    line_item.item_type = item_type
    line_item.item_id = item_id or uuid4()
    return line_item


def _make_invoice(status=InvoiceStatus.REFUNDED, line_items=None, user_id=None):
    """Create a mock invoice."""
    invoice = MagicMock()
    invoice.id = uuid4()
    invoice.user_id = user_id or uuid4()
    invoice.status = status
    invoice.line_items = line_items or []
    return invoice


def _make_container(**overrides):
    """Create a mock container with repo factories."""
    container = MagicMock()
    for name in [
        "invoice_repository",
        "subscription_repository",
        "token_balance_repository",
        "token_transaction_repository",
        "token_bundle_purchase_repository",
        "addon_subscription_repository",
        "token_service",
    ]:
        if name not in overrides:
            getattr(container, name).return_value = MagicMock()
    for name, repo in overrides.items():
        getattr(container, name).return_value = repo
    return container


def _make_service(container):
    """Create RestoreService with a registry backed by the container."""
    from vbwd.services.restore_service import RestoreService

    registry = LineItemHandlerRegistry()
    registry.register(CoreLineItemHandler(container))
    registry.register(SubscriptionLineItemHandler(container))
    return RestoreService(container, registry=registry)


class TestRestoreServiceProcessRestore:
    """Tests for RestoreService.process_restore()."""

    def test_restore_refunded_invoice(self):
        """Restore a refunded invoice marks it as PAID."""
        invoice = _make_invoice(InvoiceStatus.REFUNDED)
        invoice_repo = MagicMock()
        invoice_repo.find_by_id.return_value = invoice

        container = _make_container(invoice_repository=invoice_repo)
        service = _make_service(container)

        result = service.process_restore(
            invoice_id=invoice.id, reason="refund_canceled"
        )

        assert result.success is True
        assert result.invoice == invoice
        assert invoice.status == InvoiceStatus.PAID
        invoice_repo.save.assert_called_with(invoice)

    def test_restore_reactivates_cancelled_subscription(self):
        """Restore re-activates a cancelled subscription."""
        sub_id = uuid4()
        line_item = _make_line_item(LineItemType.SUBSCRIPTION, sub_id)
        invoice = _make_invoice(InvoiceStatus.REFUNDED, [line_item])

        subscription = MagicMock()
        subscription.id = sub_id
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = datetime(2026, 2, 10)
        plan = MagicMock()
        plan.billing_period = MagicMock()
        subscription.tarif_plan = plan

        invoice_repo = MagicMock()
        invoice_repo.find_by_id.return_value = invoice

        sub_repo = MagicMock()
        sub_repo.find_by_id.return_value = subscription

        container = _make_container(
            invoice_repository=invoice_repo,
            subscription_repository=sub_repo,
        )
        service = _make_service(container)

        result = service.process_restore(
            invoice_id=invoice.id, reason="refund_canceled"
        )

        assert result.success is True
        assert subscription.status == SubscriptionStatus.ACTIVE
        assert subscription.cancelled_at is None
        assert subscription.starts_at is not None
        assert subscription.expires_at is not None
        sub_repo.save.assert_called_with(subscription)
        assert result.items_restored["subscription"] == str(sub_id)

    def test_restore_recredits_tokens(self):
        """Restore re-credits tokens for a refunded purchase."""
        purchase_id = uuid4()
        user_id = uuid4()
        line_item = _make_line_item(LineItemType.TOKEN_BUNDLE, purchase_id)
        invoice = _make_invoice(InvoiceStatus.REFUNDED, [line_item], user_id=user_id)

        purchase = MagicMock()
        purchase.id = purchase_id
        purchase.status = PurchaseStatus.REFUNDED
        purchase.token_amount = 500

        invoice_repo = MagicMock()
        invoice_repo.find_by_id.return_value = invoice

        purchase_repo = MagicMock()
        purchase_repo.find_by_id.return_value = purchase

        token_service = MagicMock()

        container = _make_container(
            invoice_repository=invoice_repo,
            token_bundle_purchase_repository=purchase_repo,
            token_service=token_service,
        )
        service = _make_service(container)

        result = service.process_restore(
            invoice_id=invoice.id, reason="refund_canceled"
        )

        assert result.success is True
        assert purchase.status == PurchaseStatus.COMPLETED
        assert purchase.tokens_credited is True
        purchase_repo.save.assert_called_with(purchase)
        # S138.0 Inc 3: the re-credit routes through core's TokenService (it
        # used to write the balance row and the ledger entry itself, so no
        # token-movement hook ever saw a refund restore).
        token_service.credit_tokens.assert_called_once()
        assert token_service.credit_tokens.call_args.kwargs["amount"] == 500
        assert token_service.credit_tokens.call_args.kwargs["user_id"] == user_id
        assert str(purchase_id) in result.items_restored["token_bundles"]
        assert result.items_restored["tokens_credited"] == 500

    def test_restore_credits_a_user_with_no_balance_row_yet(self):
        """A user with no balance row is the service's problem, not ours.

        ``TokenService.credit_tokens`` creates the row via ``get_or_create``;
        restore just asks for the credit.
        """
        purchase_id = uuid4()
        user_id = uuid4()
        line_item = _make_line_item(LineItemType.TOKEN_BUNDLE, purchase_id)
        invoice = _make_invoice(InvoiceStatus.REFUNDED, [line_item], user_id=user_id)

        purchase = MagicMock()
        purchase.id = purchase_id
        purchase.status = PurchaseStatus.REFUNDED
        purchase.token_amount = 300

        invoice_repo = MagicMock()
        invoice_repo.find_by_id.return_value = invoice

        purchase_repo = MagicMock()
        purchase_repo.find_by_id.return_value = purchase

        token_service = MagicMock()

        container = _make_container(
            invoice_repository=invoice_repo,
            token_bundle_purchase_repository=purchase_repo,
            token_service=token_service,
        )
        service = _make_service(container)

        result = service.process_restore(
            invoice_id=invoice.id, reason="refund_canceled"
        )

        assert result.success is True
        assert token_service.credit_tokens.call_args.kwargs["amount"] == 300

    def test_restore_reactivates_addon(self):
        """Restore re-activates a cancelled add-on subscription."""
        addon_id = uuid4()
        line_item = _make_line_item(LineItemType.ADD_ON, addon_id)
        invoice = _make_invoice(InvoiceStatus.REFUNDED, [line_item])

        addon_sub = MagicMock()
        addon_sub.id = addon_id
        addon_sub.status = SubscriptionStatus.CANCELLED
        addon_sub.cancelled_at = datetime(2026, 2, 10)

        invoice_repo = MagicMock()
        invoice_repo.find_by_id.return_value = invoice

        addon_repo = MagicMock()
        addon_repo.find_by_id.return_value = addon_sub

        container = _make_container(
            invoice_repository=invoice_repo,
            addon_subscription_repository=addon_repo,
        )
        service = _make_service(container)

        result = service.process_restore(
            invoice_id=invoice.id, reason="refund_canceled"
        )

        assert result.success is True
        assert addon_sub.status == SubscriptionStatus.ACTIVE
        assert addon_sub.cancelled_at is None
        assert addon_sub.activated_at is not None
        addon_repo.save.assert_called_with(addon_sub)
        assert str(addon_id) in result.items_restored["add_ons"]

    def test_restore_rejects_non_refunded_invoice(self):
        """Restore rejects invoice that is not REFUNDED."""
        invoice = _make_invoice(InvoiceStatus.PAID)
        invoice_repo = MagicMock()
        invoice_repo.find_by_id.return_value = invoice

        container = _make_container(invoice_repository=invoice_repo)
        service = _make_service(container)

        result = service.process_restore(invoice_id=invoice.id, reason="test")

        assert result.success is False
        assert "cannot restore" in result.error.lower()

    def test_restore_rejects_missing_invoice(self):
        """Restore rejects when invoice not found."""
        invoice_repo = MagicMock()
        invoice_repo.find_by_id.return_value = None

        container = _make_container(invoice_repository=invoice_repo)
        service = _make_service(container)

        result = service.process_restore(invoice_id=uuid4(), reason="test")

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_restore_handles_mixed_items(self):
        """Restore handles invoice with subscription + tokens + add-on."""
        sub_id = uuid4()
        purchase_id = uuid4()
        addon_id = uuid4()
        user_id = uuid4()

        li_sub = _make_line_item(LineItemType.SUBSCRIPTION, sub_id)
        li_token = _make_line_item(LineItemType.TOKEN_BUNDLE, purchase_id)
        li_addon = _make_line_item(LineItemType.ADD_ON, addon_id)
        invoice = _make_invoice(
            InvoiceStatus.REFUNDED, [li_sub, li_token, li_addon], user_id=user_id
        )

        subscription = MagicMock(id=sub_id, status=SubscriptionStatus.CANCELLED)
        subscription.cancelled_at = datetime(2026, 2, 10)
        plan = MagicMock()
        plan.billing_period = MagicMock()
        subscription.tarif_plan = plan

        purchase = MagicMock(
            id=purchase_id, status=PurchaseStatus.REFUNDED, token_amount=200
        )

        addon_sub = MagicMock(id=addon_id, status=SubscriptionStatus.CANCELLED)
        addon_sub.cancelled_at = datetime(2026, 2, 10)

        sub_repo = MagicMock(find_by_id=MagicMock(return_value=subscription))
        purchase_repo = MagicMock(find_by_id=MagicMock(return_value=purchase))
        addon_repo = MagicMock(find_by_id=MagicMock(return_value=addon_sub))
        token_service = MagicMock()

        invoice_repo = MagicMock(find_by_id=MagicMock(return_value=invoice))

        container = _make_container(
            invoice_repository=invoice_repo,
            subscription_repository=sub_repo,
            token_bundle_purchase_repository=purchase_repo,
            addon_subscription_repository=addon_repo,
            token_service=token_service,
        )
        service = _make_service(container)

        result = service.process_restore(
            invoice_id=invoice.id, reason="refund_canceled"
        )

        assert result.success is True
        assert result.items_restored["subscription"] == str(sub_id)
        assert str(purchase_id) in result.items_restored["token_bundles"]
        assert str(addon_id) in result.items_restored["add_ons"]
        assert result.items_restored["tokens_credited"] == 200
        assert invoice.status == InvoiceStatus.PAID
        assert subscription.status == SubscriptionStatus.ACTIVE
        assert purchase.status == PurchaseStatus.COMPLETED
        assert addon_sub.status == SubscriptionStatus.ACTIVE
        assert token_service.credit_tokens.call_args.kwargs["amount"] == 200
