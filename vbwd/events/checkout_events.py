"""Checkout domain events."""
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID
from vbwd.events.domain import DomainEvent


@dataclass
class CheckoutRequestedEvent(DomainEvent):
    """
    Event emitted when user requests checkout.

    Creates pending subscription, token bundle purchases, and add-on subscriptions.
    All items remain pending until payment is confirmed.
    """

    user_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None
    token_bundle_ids: List[UUID] = field(default_factory=list)
    add_on_ids: List[UUID] = field(default_factory=list)
    currency: str = "USD"
    payment_method_code: Optional[str] = None
    # Generic coupon code (like payment_method_code, core names no discount
    # domain) — the checkout handler reduces the price via the core
    # checkout_price_adjustment_registry; empty/None when no coupon.
    coupon_code: Optional[str] = None

    def __post_init__(self):
        self.name = "checkout.requested"
        super().__post_init__()


@dataclass
class CheckoutCompletedEvent(DomainEvent):
    """
    Event emitted when checkout is successfully created.

    Contains IDs of all created pending items.
    """

    user_id: Optional[UUID] = None
    subscription_id: Optional[UUID] = None
    invoice_id: Optional[UUID] = None
    token_bundle_purchase_ids: List[UUID] = field(default_factory=list)
    addon_subscription_ids: List[UUID] = field(default_factory=list)

    def __post_init__(self):
        self.name = "checkout.completed"
        super().__post_init__()


@dataclass
class CheckoutFailedEvent(DomainEvent):
    """Event emitted when checkout creation fails."""

    user_id: Optional[UUID] = None
    error: Optional[str] = None
    error_type: Optional[str] = None

    def __post_init__(self):
        self.name = "checkout.failed"
        super().__post_init__()
