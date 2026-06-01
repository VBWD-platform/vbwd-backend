"""Foundational payment-method catalog seeder.

Mirrors :mod:`vbwd.services.country_seeder`: idempotent, service-layer seed of
the baseline payment methods every install needs. Currently that is the manual
``invoice`` method (offline / bank-transfer style) — the always-available
fallback that does not depend on any payment plugin being enabled.

Ungated foundational data (NOT behind ``TEST_DATA_SEED``): a fresh install must
be able to issue an invoice before any provider plugin is configured.
"""
from dataclasses import dataclass
from uuid import uuid4

from vbwd.models.payment_method import PaymentMethod

# (code, name, is_default) for the baseline, plugin-independent methods.
DEFAULT_PAYMENT_METHODS = [
    ("invoice", "Invoice", True),
]


@dataclass(frozen=True)
class PaymentMethodSeedResult:
    """Counts from a seeder run (idempotent re-runs report created=0)."""

    created: int = 0


def seed_payment_methods(session) -> PaymentMethodSeedResult:
    """Idempotently ensure the baseline payment methods exist.

    For each ``(code, name, is_default)`` in :data:`DEFAULT_PAYMENT_METHODS`,
    create an active :class:`PaymentMethod` if none exists for that code.
    Existing rows are left untouched, so an operator's edits survive a re-run.

    Safe to re-run; a second run creates nothing new.
    """
    created = 0
    for position, (code, name, is_default) in enumerate(DEFAULT_PAYMENT_METHODS):
        existing = session.query(PaymentMethod).filter_by(code=code).first()
        if existing:
            continue

        session.add(
            PaymentMethod(
                id=uuid4(),
                code=code,
                name=name,
                is_active=True,
                is_default=is_default,
                position=position,
            )
        )
        created += 1

    session.commit()

    return PaymentMethodSeedResult(created=created)
