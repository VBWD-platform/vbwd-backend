"""Refund service — orchestrates full invoice refund."""
from typing import Optional, Dict, Any
from uuid import UUID

from vbwd.events.line_item_registry import (
    LineItemContext,
    LineItemHandlerRegistry,
    line_item_registry,
)
from vbwd.models.enums import (
    InvoiceStatus,
    LineItemType,
    PurchaseStatus,
)
from vbwd.repositories.invoice_repository import InvoiceRepository
from vbwd.repositories.token_bundle_purchase_repository import (
    TokenBundlePurchaseRepository,
)
from vbwd.services.token_service import TokenService


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
    2. Pre-check token balance
    3. Mark invoice as REFUNDED
    4. Delegate line item reversal to registry
    """

    def __init__(
        self,
        invoice_repo: InvoiceRepository,
        token_service: TokenService,
        purchase_repo: TokenBundlePurchaseRepository,
        container=None,
        registry: LineItemHandlerRegistry | None = None,
    ):
        self._invoice_repo = invoice_repo
        self._token_service = token_service
        self._purchase_repo = purchase_repo
        self._container = container
        self._registry = registry or line_item_registry

    def process_refund(self, invoice_id: UUID, refund_reference: str) -> RefundResult:
        """Process a full refund for an invoice."""
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

        # 2. Pre-check: ensure user has enough tokens
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

        # 4. Delegate line item reversal to registry
        context = LineItemContext(
            invoice=invoice,
            user_id=invoice.user_id,
            container=self._container,
        )
        items_reversed: Dict[str, Any] = {
            "subscription": None,
            "token_bundles": [],
            "add_ons": [],
            "tokens_debited": 0,
        }

        for line_item in invoice.line_items:  # type: ignore[attr-defined]
            result = self._registry.process_reversal(line_item, context)
            if result.success and not result.skipped:
                data = result.data
                if "subscription_id" in data:
                    items_reversed["subscription"] = data["subscription_id"]
                if "purchase_id" in data:
                    items_reversed["token_bundles"].append(data["purchase_id"])
                if "addon_subscription_id" in data:
                    items_reversed["add_ons"].append(data["addon_subscription_id"])
                items_reversed["tokens_debited"] += data.get("tokens_debited", 0)

        return RefundResult(
            success=True,
            invoice=invoice,
            items_reversed=items_reversed,
        )

    def calculate_tokens_to_debit(self, invoice) -> int:
        """Calculate total tokens that need to be deducted for this refund.

        Only counts TOKEN_BUNDLE items (core). Subscription default_tokens
        are handled by the subscription plugin's line item handler.

        Public for the admin refund pre-check (S23). Callers use this to
        validate the user has enough tokens BEFORE invoking the payment
        provider so the provider isn't charged for a refund that will
        then fail at token-debit time.
        """
        total = 0
        for line_item in invoice.line_items:
            if line_item.item_type == LineItemType.TOKEN_BUNDLE:
                purchase = self._purchase_repo.find_by_id(line_item.item_id)
                if purchase and purchase.status == PurchaseStatus.COMPLETED:
                    total += purchase.token_amount
        return total

    # Backward-compat alias — the underscore-private form was used by the
    # admin refund route inline. Kept so external callers don't break;
    # delete when no callers remain.
    _calculate_tokens_to_debit = calculate_tokens_to_debit
