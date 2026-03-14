"""Restore service — reverses a refund, restoring invoice and all items."""
from datetime import timedelta
from src.utils.datetime_utils import utcnow
from typing import Optional, Dict, Any
from uuid import UUID, uuid4

from src.models.enums import (
    InvoiceStatus,
    LineItemType,
    SubscriptionStatus,
    PurchaseStatus,
    TokenTransactionType,
)


class RestoreResult:
    """Result of a restore operation."""

    def __init__(
        self,
        success: bool,
        invoice=None,
        items_restored: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        self.success = success
        self.invoice = invoice
        self.items_restored = items_restored
        self.error = error


class RestoreService:
    """Service for restoring a refunded invoice.

    Reverses a refund — restores the invoice to PAID and re-activates
    all line items (subscriptions, tokens, add-ons).
    """

    def __init__(self, container):
        self._container = container

    def process_restore(self, invoice_id: UUID, reason: str = "") -> RestoreResult:
        """
        Restore a refunded invoice back to PAID state.

        Args:
            invoice_id: UUID of the invoice to restore.
            reason: Reason for the restoration (e.g. 'refund_canceled').

        Returns:
            RestoreResult with invoice and items_restored dict.
        """
        invoice_repo = self._container.invoice_repository()

        # 1. Fetch and validate invoice
        invoice = invoice_repo.find_by_id(str(invoice_id))
        if not invoice:
            return RestoreResult(success=False, error=f"Invoice {invoice_id} not found")

        if invoice.status != InvoiceStatus.REFUNDED:
            return RestoreResult(
                success=False,
                error=f"Cannot restore: invoice status is {invoice.status.value}, expected refunded",
            )

        # 2. Mark invoice as paid again
        invoice.status = InvoiceStatus.PAID
        invoice_repo.save(invoice)

        # 3. Restore line items
        items_restored: dict[str, object] = {
            "subscription": None,
            "token_bundles": [],
            "add_ons": [],
            "tokens_credited": 0,
        }

        for line_item in invoice.line_items:
            if line_item.item_type == LineItemType.SUBSCRIPTION:
                self._restore_subscription(line_item, items_restored)
            elif line_item.item_type == LineItemType.TOKEN_BUNDLE:
                self._restore_token_bundle(line_item, invoice.user_id, items_restored)
            elif line_item.item_type == LineItemType.ADD_ON:
                self._restore_addon(line_item, items_restored)

        return RestoreResult(
            success=True, invoice=invoice, items_restored=items_restored
        )

    def _restore_subscription(self, line_item, items_restored):
        """Re-activate a cancelled subscription."""
        sub_repo = self._container.subscription_repository()
        subscription = sub_repo.find_by_id(line_item.item_id)
        if subscription and subscription.status == SubscriptionStatus.CANCELLED:
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.cancelled_at = None
            # Recalculate expiration from now
            if subscription.tarif_plan:
                from src.services.subscription_service import SubscriptionService

                period_days = SubscriptionService.PERIOD_DAYS.get(
                    subscription.tarif_plan.billing_period, 30
                )
                subscription.starts_at = utcnow()
                subscription.expires_at = utcnow() + timedelta(days=period_days)
            sub_repo.save(subscription)
            items_restored["subscription"] = str(subscription.id)

    def _restore_token_bundle(self, line_item, user_id, items_restored):
        """Re-credit tokens for a refunded purchase."""
        purchase_repo = self._container.token_bundle_purchase_repository()
        purchase = purchase_repo.find_by_id(line_item.item_id)
        if purchase and purchase.status == PurchaseStatus.REFUNDED:
            purchase.status = PurchaseStatus.COMPLETED
            purchase.tokens_credited = True
            purchase_repo.save(purchase)

            # Re-credit tokens
            from src.models.user_token_balance import UserTokenBalance, TokenTransaction

            token_repo = self._container.token_balance_repository()
            token_tx_repo = self._container.token_transaction_repository()

            balance = token_repo.find_by_user_id(user_id)
            if not balance:
                balance = UserTokenBalance(id=uuid4(), user_id=user_id, balance=0)
            balance.balance += purchase.token_amount
            token_repo.save(balance)

            transaction = TokenTransaction(
                id=uuid4(),
                user_id=user_id,
                amount=purchase.token_amount,
                transaction_type=TokenTransactionType.PURCHASE,
                reference_id=purchase.id,
                description=f"Refund reversed: {purchase.token_amount} tokens restored",
            )
            token_tx_repo.save(transaction)

            items_restored["token_bundles"].append(str(purchase.id))
            items_restored["tokens_credited"] += purchase.token_amount

    def _restore_addon(self, line_item, items_restored):
        """Re-activate a cancelled add-on subscription."""
        addon_repo = self._container.addon_subscription_repository()
        addon_sub = addon_repo.find_by_id(line_item.item_id)
        if addon_sub and addon_sub.status == SubscriptionStatus.CANCELLED:
            addon_sub.status = SubscriptionStatus.ACTIVE
            addon_sub.cancelled_at = None
            addon_sub.activated_at = utcnow()
            addon_repo.save(addon_sub)
            items_restored["add_ons"].append(str(addon_sub.id))
