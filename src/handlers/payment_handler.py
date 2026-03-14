"""Payment event handlers."""
from datetime import timedelta
from typing import Any
from src.utils.datetime_utils import utcnow
from src.events.domain import DomainEvent, EventResult, IEventHandler
from src.events.payment_events import PaymentCapturedEvent
from src.models.enums import LineItemType, SubscriptionStatus, PurchaseStatus


class PaymentCapturedHandler(IEventHandler):
    """
    Handler for payment capture events.

    Activates all pending items on the invoice:
    - Subscription → active
    - Token bundles → tokens credited
    - Add-ons → active
    """

    def __init__(self, container):
        """
        Initialize handler with DI container.

        Args:
            container: DI container to get services at request time
        """
        self._container = container

    def _get_services(self):
        """Get fresh services for the current request session."""
        return {
            "invoice": self._container.invoice_repository(),
            "subscription": self._container.subscription_repository(),
            "token": self._container.token_balance_repository(),
            "token_transaction": self._container.token_transaction_repository(),
            "token_bundle_purchase": self._container.token_bundle_purchase_repository(),
            "addon_subscription": self._container.addon_subscription_repository(),
        }

    def can_handle(self, event: DomainEvent) -> bool:
        """Check if this handler can handle payment.captured events."""
        return isinstance(event, PaymentCapturedEvent)

    def handle(self, event: DomainEvent) -> EventResult:
        """
        Handle payment capture.

        Processes each line item on the invoice:
        1. Marks invoice as paid
        2. Activates subscription
        3. Credits tokens from bundle purchases
        4. Activates add-on subscriptions

        Args:
            event: PaymentCapturedEvent

        Returns:
            EventResult with activation details or error
        """
        if not isinstance(event, PaymentCapturedEvent):
            return EventResult.error_result("Invalid event type")

        try:
            repos = self._get_services()

            # 1. Get and validate invoice
            invoice = repos["invoice"].find_by_id(event.invoice_id)
            if not invoice:
                return EventResult.error_result(f"Invoice {event.invoice_id} not found")

            # Invoice may already be marked paid by the route/service that
            # dispatched this event — that's expected. Only update payment
            # metadata if it hasn't been set yet.
            if invoice.status.value != "PAID":
                invoice.status = invoice.status.__class__("PAID")
                invoice.payment_ref = event.payment_reference
                invoice.paid_at = utcnow()
                repos["invoice"].save(invoice)

            items_activated: dict[str, Any] = {
                "subscription": None,
                "token_bundles": [],
                "add_ons": [],
                "tokens_credited": 0,
            }

            # 3. Process each line item
            for line_item in invoice.line_items:
                if line_item.item_type == LineItemType.SUBSCRIPTION:
                    # Activate subscription
                    subscription = repos["subscription"].find_by_id(line_item.item_id)
                    if subscription and subscription.status in (
                        SubscriptionStatus.PENDING,
                        SubscriptionStatus.TRIALING,  # trial → paid conversion
                        SubscriptionStatus.CANCELLED,  # post-trial conversion
                    ):
                        # Cancel subscriptions in the same is_single categories only.
                        # Multi-subscription categories (is_single=False) allow
                        # concurrent subscriptions and must not be cancelled.
                        plan = subscription.tarif_plan
                        categories = getattr(plan, "categories", []) if plan else []
                        for category in categories:
                            if category.is_single:
                                category_plan_ids = [
                                    str(p.id) for p in category.tarif_plans
                                ]
                                conflicting = repos[
                                    "subscription"
                                ].find_active_by_user_in_category(
                                    invoice.user_id, category_plan_ids
                                )
                                for prev in conflicting:
                                    if str(prev.id) != str(subscription.id):
                                        prev.status = SubscriptionStatus.CANCELLED
                                        prev.cancelled_at = utcnow()
                                        repos["subscription"].save(prev)

                        subscription.status = SubscriptionStatus.ACTIVE
                        subscription.started_at = utcnow()
                        # Calculate expiration based on plan
                        if subscription.tarif_plan:
                            from src.services.subscription_service import (
                                SubscriptionService,
                            )

                            period_days = SubscriptionService.PERIOD_DAYS.get(
                                subscription.tarif_plan.billing_period, 30
                            )

                            subscription.expires_at = utcnow() + timedelta(
                                days=period_days
                            )
                        repos["subscription"].save(subscription)
                        items_activated["subscription"] = str(subscription.id)

                        # Credit default tokens from plan features
                        features = subscription.tarif_plan.features or {}
                        default_tokens = (
                            features.get("default_tokens", 0)
                            if isinstance(features, dict)
                            else 0
                        )
                        if default_tokens > 0:
                            from src.models.user_token_balance import (
                                UserTokenBalance,
                                TokenTransaction,
                            )
                            from src.models.enums import TokenTransactionType
                            from uuid import uuid4

                            balance = repos["token"].find_by_user_id(invoice.user_id)
                            if not balance:
                                balance = UserTokenBalance(
                                    id=uuid4(),
                                    user_id=invoice.user_id,
                                    balance=0,
                                )
                            balance.balance += default_tokens
                            repos["token"].save(balance)

                            transaction = TokenTransaction(
                                id=uuid4(),
                                user_id=invoice.user_id,
                                amount=default_tokens,
                                transaction_type=TokenTransactionType.SUBSCRIPTION,
                                reference_id=subscription.id,
                                description=f"Plan tokens: {subscription.tarif_plan.name}",
                            )
                            repos["token_transaction"].save(transaction)

                            items_activated["tokens_credited"] += default_tokens

                elif line_item.item_type == LineItemType.TOKEN_BUNDLE:
                    # Complete token bundle purchase and credit tokens
                    purchase = repos["token_bundle_purchase"].find_by_id(
                        line_item.item_id
                    )
                    if purchase and purchase.status == PurchaseStatus.PENDING:
                        # Mark purchase as completed
                        purchase.status = PurchaseStatus.COMPLETED
                        purchase.completed_at = utcnow()
                        purchase.tokens_credited = True
                        repos["token_bundle_purchase"].save(purchase)

                        # Credit tokens to user balance
                        from src.models.user_token_balance import (
                            UserTokenBalance,
                            TokenTransaction,
                        )
                        from src.models.enums import TokenTransactionType
                        from uuid import uuid4

                        balance = repos["token"].find_by_user_id(invoice.user_id)
                        if not balance:
                            balance = UserTokenBalance(
                                id=uuid4(),
                                user_id=invoice.user_id,
                                balance=0,
                            )
                        balance.balance += purchase.token_amount
                        repos["token"].save(balance)

                        # Record transaction
                        transaction = TokenTransaction(
                            id=uuid4(),
                            user_id=invoice.user_id,
                            amount=purchase.token_amount,
                            transaction_type=TokenTransactionType.PURCHASE,
                            reference_id=purchase.id,
                            description=f"Token bundle purchase: {purchase.token_amount} tokens",
                        )
                        repos["token_transaction"].save(transaction)

                        items_activated["token_bundles"].append(str(purchase.id))
                        items_activated["tokens_credited"] += purchase.token_amount

                elif line_item.item_type == LineItemType.ADD_ON:
                    # Activate add-on subscription
                    addon_sub = repos["addon_subscription"].find_by_id(
                        line_item.item_id
                    )
                    if addon_sub and addon_sub.status == SubscriptionStatus.PENDING:
                        addon_sub.status = SubscriptionStatus.ACTIVE
                        addon_sub.activated_at = utcnow()
                        repos["addon_subscription"].save(addon_sub)
                        items_activated["add_ons"].append(str(addon_sub.id))

            return EventResult.success_result(
                {
                    "invoice_id": str(invoice.id),
                    "status": "paid",
                    "payment_reference": event.payment_reference,
                    "items_activated": items_activated,
                }
            )

        except Exception as e:
            return EventResult.error_result(str(e))
