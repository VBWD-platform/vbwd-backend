"""Payment-provision referral port (S92 Track A — INERT foundation stub).

This module is the **design-only foundation** for the payment-provision referral
base: the system that tracks the provision VBWD owes its partners when customer
payments settle through a provider's native referral / Connect program (Stripe
Connect application fees / transfers, PayPal Partner revenue share, ...).

**It is intentionally inert.** There is no concrete implementation, nothing is
registered in the DI container, and nothing in the request path calls it. It
exists so the monolith has a stable seam to later *emit* the partner attribution
it already knows about (which charge/order settled for which partner), while the
actual ledger lives in a separate deployable (`vbwd-provision-base`).

Live provider wiring (Stripe Connect platform / PayPal Partner webhooks, the
running ledger service) is deferred to a follow-up sprint gated on external
prerequisites — see the architecture doc and decisions DA-1..DA-4:
``docs/architecture/payment-provision-referral-base.md``.

Core-agnosticism note: this is a generic financial-attribution port (no plugin
vocabulary, no ``from plugins.*`` import), so it does not breach the core
agnosticism oracle. It is unused on purpose; do not wire a concrete provider into
core — concrete adapters belong in the future provision-base service / a payment
plugin, not here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PartnerAttribution:
    """One settled payment attributed to a partner, for the provision ledger.

    All monetary fields are full-precision ``Decimal`` in ``currency``; rounding
    is the ledger's concern, not the emitter's. ``source_ref`` is the provider's
    own identifier (charge / transfer / order id) and is the idempotency key for
    replay-safe ingestion downstream.
    """

    partner_ref: str
    """The partner / connected-account identifier in the provider's namespace."""

    provider: str
    """Settlement provider, e.g. ``"stripe_connect"`` or ``"paypal_partner"``."""

    source_ref: str
    """Provider charge / transfer / order id — the idempotency key downstream."""

    gross_amount: Decimal
    """Gross amount the customer paid."""

    fee_amount: Decimal
    """Provider/platform fee withheld from the gross."""

    provision_owed: Decimal
    """Provision VBWD owes the partner for this settlement."""

    currency: str
    """ISO-4217 currency code of the amounts above."""


class IPaymentReferralProvider(ABC):
    """Port the monolith would use to emit partner attribution (INERT stub).

    No concrete implementation exists yet (S92 Track A is design + foundation
    only). A future ``StripeConnectProvider`` / ``PayPalReferralProvider`` — most
    likely living in the standalone ``vbwd-provision-base`` service rather than in
    core — will implement this. Until then ``is_enabled()`` returns ``False`` for
    every (non-existent) implementation and callers must no-op when disabled.
    """

    @abstractmethod
    def is_enabled(self) -> bool:
        """Whether partner-provision emission is wired and active.

        Always treat a missing/disabled provider as a no-op: the monolith must
        function identically whether or not a provision base is attached.
        """
        raise NotImplementedError

    @abstractmethod
    def record_attribution(self, attribution: PartnerAttribution) -> None:
        """Emit one ``PartnerAttribution`` to the provision ledger.

        Implementations MUST be idempotent on ``attribution.source_ref`` so that
        provider webhook replays do not double-count a settlement.
        """
        raise NotImplementedError
