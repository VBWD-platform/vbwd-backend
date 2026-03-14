"""Refund service — orchestrates full invoice refund."""
from src.utils.datetime_utils import utcnow
from typing import Optional, Dict, Any
from uuid import UUID

from src.models.enums import (
    InvoiceStatus,
    LineItemType,
    SubscriptionStatus,
    PurchaseStatus,
    TokenTransactionType,
)
from src.repositories.invoice_repository import InvoiceRepository
from src.repositories.subscription_repository import SubscriptionRepository
from src.repositories.token_bundle_purchase_repository import (
    TokenBundlePurchaseRepository,
)
from src.repositories.addon_subscription_repository import AddOnSubscriptionRepository
from src.services.token_service import TokenService


class RefundResult:
    """Result of a refund operation."""

    def __init__(
        self,
        success: bool,
        invoice=None,
        items_reversed: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        self.success = success
        self.invoice = invoice
        self.items_reversed = items_reversed
        self.error = error


class RefundService:
    """Service for processing invoice refunds.

    Orchestrates the full refund flow:
    1. Validate invoice status
    2. Mark invoice as REFUNDED
    3. Reverse all activated line items (subscriptions, tokens, add-ons)
    """

    def __init__(
        self,
        invoice_repo: InvoiceRepository,
        subscription_repo: SubscriptionRepository,
        token_service: TokenService,
        purchase_repo: TokenBundlePurchaseRepository,
        addon_sub_repo: AddOnSubscriptionRepository,
    ):
        self._invoice_repo = invoice_repo
        self._subscription_repo = subscription_repo
        self._token_service = token_service
        self._purchase_repo = purchase_repo
        self._addon_sub_repo = addon_sub_repo

    def process_refund(self, invoice_id: UUID, refund_reference: str) -> RefundResult:
        """
        Process a full refund for an invoice.

        Args:
            invoice_id: UUID of the invoice to refund.
            refund_reference: External refund reference string.

        Returns:
            RefundResult with invoice and items_reversed dict.
        """
        # 1. Fetch and validate invoice
        invoice = self._invoice_repo.find_by_id(str(invoice_id))
        if not invoice:
            return RefundResult(
                success=False,
                error=f"Invoice {invoice_id} not found",
            )

        if invoice.status != InvoiceStatus.PAID:
            return RefundResult(
                success=False,
                error=f"Cannot refund: invoice status is {invoice.status.value}",
            )

        # 2. Pre-check: ensure user has enough tokens to cover subscription default_tokens
        total_tokens_to_debit = self._calculate_tokens_to_debit(invoice)
        if total_tokens_to_debit > 0:
            current_balance = self._token_service.get_balance(invoice.user_id)
            if current_balance < total_tokens_to_debit:
                return RefundResult(
                    success=False,
                    error=(
                        f"Insufficient token balance for refund. "
                        f"User has {current_balance} tokens but {total_tokens_to_debit} "
                        f"need to be deducted. User must purchase more tokens first."
                    ),
                )

        # 3. Mark invoice as refunded
        invoice.mark_refunded()
        self._invoice_repo.save(invoice)

        # 4. Reverse line items
        items_reversed: dict[str, object] = {
            "subscription": None,
            "token_bundles": [],
            "add_ons": [],
            "tokens_debited": 0,
        }

        for line_item in invoice.line_items:  # type: ignore[attr-defined]
            if line_item.item_type == LineItemType.SUBSCRIPTION:
                self._reverse_subscription(line_item, invoice.user_id, items_reversed)
            elif line_item.item_type == LineItemType.TOKEN_BUNDLE:
                self._reverse_token_bundle(line_item, invoice.user_id, items_reversed)
            elif line_item.item_type == LineItemType.ADD_ON:
                self._reverse_addon(line_item, items_reversed)

        return RefundResult(
            success=True,
            invoice=invoice,
            items_reversed=items_reversed,
        )

    def _calculate_tokens_to_debit(self, invoice) -> int:
        """Calculate total tokens that need to be deducted for this refund."""
        total = 0
        for line_item in invoice.line_items:
            if line_item.item_type == LineItemType.SUBSCRIPTION:
                subscription = self._subscription_repo.find_by_id(line_item.item_id)
                if subscription and subscription.status == SubscriptionStatus.ACTIVE:
                    if subscription.tarif_plan:
                        features = subscription.tarif_plan.features or {}
                        default_tokens = (
                            features.get("default_tokens", 0)
                            if isinstance(features, dict)
                            else 0
                        )
                        total += default_tokens
            elif line_item.item_type == LineItemType.TOKEN_BUNDLE:
                purchase = self._purchase_repo.find_by_id(line_item.item_id)
                if purchase and purchase.status == PurchaseStatus.COMPLETED:
                    total += purchase.token_amount
        return total

    def _reverse_subscription(self, line_item, user_id, items_reversed):
        """Cancel an active subscription and debit default tokens."""
        subscription = self._subscription_repo.find_by_id(line_item.item_id)
        if subscription and subscription.status == SubscriptionStatus.ACTIVE:
            # Debit default_tokens from user balance
            if subscription.tarif_plan:
                features = subscription.tarif_plan.features or {}
                default_tokens = (
                    features.get("default_tokens", 0)
                    if isinstance(features, dict)
                    else 0
                )
                if default_tokens > 0:
                    self._token_service.debit_tokens(
                        user_id=user_id,
                        amount=default_tokens,
                        transaction_type=TokenTransactionType.REFUND,
                        reference_id=subscription.id,
                        description=f"Refund plan tokens: {subscription.tarif_plan.name}",
                    )
                    items_reversed["tokens_debited"] += default_tokens

            subscription.status = SubscriptionStatus.CANCELLED
            subscription.cancelled_at = utcnow()
            self._subscription_repo.save(subscription)
            items_reversed["subscription"] = str(subscription.id)

    def _reverse_token_bundle(self, line_item, user_id, items_reversed):
        """Mark purchase as refunded and debit tokens."""
        purchase = self._purchase_repo.find_by_id(line_item.item_id)
        if purchase and purchase.status == PurchaseStatus.COMPLETED:
            purchase.status = PurchaseStatus.REFUNDED
            self._purchase_repo.save(purchase)

            actual_debited = self._token_service.refund_tokens(
                user_id=user_id,
                amount=purchase.token_amount,
                reference_id=purchase.id,
                description=f"Refund: {purchase.token_amount} tokens",
            )

            items_reversed["token_bundles"].append(str(purchase.id))
            items_reversed["tokens_debited"] += actual_debited

    def _reverse_addon(self, line_item, items_reversed):
        """Cancel an active add-on subscription."""
        addon_sub = self._addon_sub_repo.find_by_id(line_item.item_id)
        if addon_sub and addon_sub.status == SubscriptionStatus.ACTIVE:
            addon_sub.status = SubscriptionStatus.CANCELLED
            addon_sub.cancelled_at = utcnow()
            self._addon_sub_repo.save(addon_sub)
            items_reversed["add_ons"].append(str(addon_sub.id))
