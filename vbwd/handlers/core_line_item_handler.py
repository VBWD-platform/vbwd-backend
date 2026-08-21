"""Core line item handler — TOKEN_BUNDLE only.

SUBSCRIPTION and ADD_ON are handled by the subscription plugin's
SubscriptionLineItemHandler (Sprint 04b).
"""
import logging

from vbwd.events.line_item_registry import (
    ILineItemHandler,
    LineItemContext,
    LineItemResult,
)
from vbwd.models.enums import (
    LineItemType,
    PurchaseStatus,
    TokenTransactionType,
)
from vbwd.utils.datetime_utils import utcnow

logger = logging.getLogger(__name__)


class CoreLineItemHandler(ILineItemHandler):
    """Handles TOKEN_BUNDLE line items only.

    Token economy is core infrastructure — not a plugin concern.
    """

    def __init__(self, container):
        self._container = container

    def can_handle_line_item(self, line_item, context: LineItemContext) -> bool:
        return line_item.item_type == LineItemType.TOKEN_BUNDLE

    def activate_line_item(self, line_item, context: LineItemContext) -> LineItemResult:
        return self._activate_token_bundle(line_item, context)

    def reverse_line_item(self, line_item, context: LineItemContext) -> LineItemResult:
        return self._reverse_token_bundle(line_item, context)

    def restore_line_item(self, line_item, context: LineItemContext) -> LineItemResult:
        return self._restore_token_bundle(line_item, context)

    def resolve_catalog_item_id(self, line_item):
        """TOKEN_BUNDLE → its bundle id. None for any other type."""
        if line_item.item_type != LineItemType.TOKEN_BUNDLE:
            return None
        from vbwd.models.token_bundle_purchase import TokenBundlePurchase

        purchase = self._db_session().get(TokenBundlePurchase, line_item.item_id)
        return str(purchase.bundle_id) if purchase else None

    @staticmethod
    def _db_session():
        from vbwd.extensions import db

        return db.session

    # ── Activation ────────────────────────────────────────────────────────

    def _activate_token_bundle(
        self, line_item, context: LineItemContext
    ) -> LineItemResult:
        purchase_repo = self._container.token_bundle_purchase_repository()
        purchase = purchase_repo.find_by_id(line_item.item_id)
        if not purchase or purchase.status != PurchaseStatus.PENDING:
            return LineItemResult(success=True, data={})

        purchase.status = PurchaseStatus.COMPLETED
        purchase.completed_at = utcnow()
        purchase.tokens_credited = True
        purchase_repo.save(purchase)

        token_service = self._container.token_service()
        token_service.credit_tokens(
            user_id=context.user_id,
            amount=purchase.token_amount,
            transaction_type=TokenTransactionType.PURCHASE,
            reference_id=purchase.id,
            description=f"Token bundle purchase: {purchase.token_amount} tokens",
        )

        return LineItemResult(
            success=True,
            data={
                "purchase_id": str(purchase.id),
                "tokens_credited": purchase.token_amount,
            },
        )

    # ── Reversal (refund) ─────────────────────────────────────────────────

    def _reverse_token_bundle(
        self, line_item, context: LineItemContext
    ) -> LineItemResult:
        purchase_repo = self._container.token_bundle_purchase_repository()
        purchase = purchase_repo.find_by_id(line_item.item_id)
        if not purchase or purchase.status != PurchaseStatus.COMPLETED:
            return LineItemResult(success=True, data={})

        purchase.status = PurchaseStatus.REFUNDED
        purchase_repo.save(purchase)

        token_service = self._container.token_service()
        actual_debited = token_service.refund_tokens(
            user_id=context.user_id,
            amount=purchase.token_amount,
            reference_id=purchase.id,
            description=f"Refund: {purchase.token_amount} tokens",
        )

        return LineItemResult(
            success=True,
            data={
                "purchase_id": str(purchase.id),
                "tokens_debited": actual_debited,
            },
        )

    # ── Restoration (refund reversal) ─────────────────────────────────────

    def _restore_token_bundle(
        self, line_item, context: LineItemContext
    ) -> LineItemResult:
        purchase_repo = self._container.token_bundle_purchase_repository()
        purchase = purchase_repo.find_by_id(line_item.item_id)
        if not purchase or purchase.status != PurchaseStatus.REFUNDED:
            return LineItemResult(success=True, data={})

        purchase.status = PurchaseStatus.COMPLETED
        purchase.tokens_credited = True
        purchase_repo.save(purchase)

        token_service = self._container.token_service()
        token_service.credit_tokens(
            user_id=context.user_id,
            amount=purchase.token_amount,
            transaction_type=TokenTransactionType.PURCHASE,
            reference_id=purchase.id,
            description=f"Refund reversed: {purchase.token_amount} tokens restored",
        )

        return LineItemResult(
            success=True,
            data={
                "purchase_id": str(purchase.id),
                "tokens_credited": purchase.token_amount,
            },
        )
