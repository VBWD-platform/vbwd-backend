"""Core German VAT tax seeder.

Idempotently seeds the foundational German VAT tax reference data into
``vbwd_tax``. Ungated — German VAT is default reference data on every
instance, prod included, just like the country catalog and the RBAC
default roles. Safe to re-run on every deploy after ``flask db upgrade``;
a second run creates nothing new (upsert by ``code``, existing rows
untouched, so an operator's edits survive a re-run).

This module is the single source of truth for the default German VAT tax
catalog.
"""
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from vbwd.models.tax import Tax


@dataclass(frozen=True)
class _TaxSeed:
    """One entry in the default German VAT catalog (keyed by ``code``)."""

    code: str
    name: str
    rate: Decimal
    country_code: str
    tax_class: str
    is_active: bool
    is_inclusive: bool


# Default German VAT catalog — the single source of truth. Both entries are
# concrete, sellable-linkable ``Tax`` rows; ``tax_class`` is a denormalized
# grouping LABEL (not a FK), following the flattened tax schema.
TAXES = [
    _TaxSeed(
        code="VAT_DE",
        name="VAT Germany (19%)",
        rate=Decimal("19.00"),
        country_code="DE",
        tax_class="standard",
        is_active=True,
        is_inclusive=False,
    ),
    _TaxSeed(
        code="VAT_DE_7",
        name="VAT Germany (7%)",
        rate=Decimal("7.00"),
        country_code="DE",
        tax_class="reduced",
        is_active=True,
        is_inclusive=False,
    ),
]


@dataclass(frozen=True)
class TaxSeedResult:
    """Counts from a seeder run (idempotent re-runs report created=0)."""

    taxes_created: int = 0


def seed_taxes(session) -> TaxSeedResult:
    """Idempotently upsert the default German VAT tax catalog.

    For each entry in :data:`TAXES`, create a :class:`Tax` if none exists for
    that ``code``. Existing rows are left untouched, so an operator's edits
    (rate, name, active flag) survive a re-run.

    Safe to re-run; a second run creates nothing new.
    """
    taxes_created = 0
    for entry in TAXES:
        existing = session.query(Tax).filter_by(code=entry.code).first()
        if existing:
            continue

        session.add(
            Tax(
                id=uuid4(),
                code=entry.code,
                name=entry.name,
                rate=entry.rate,
                country_code=entry.country_code,
                tax_class=entry.tax_class,
                is_active=entry.is_active,
                is_inclusive=entry.is_inclusive,
            )
        )
        taxes_created += 1

    session.commit()

    return TaxSeedResult(taxes_created=taxes_created)
