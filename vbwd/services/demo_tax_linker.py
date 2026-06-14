"""Core demo-tax linker (S85.4).

The single home for the canonical demo VAT code and the idempotent
"link this tax to these sellables" operation. The core token-bundle seeder
and every plugin catalog seeder use this helper so demo prices carry tax (the
S85.4 disclosure shows ``gross > net``).

Agnostic by design: the linker looks the canonical :class:`Tax` up by ``code``
through the core :class:`TaxRepository`, so a plugin links tax to ITS own
sellables without importing core's ``Tax`` model directly and without importing
any other plugin. ``Tax`` is a core model, so seeding it lives in
``vbwd.services.tax_seeder``; this module only links it.

Idempotent: a sellable that already carries the canonical VAT is not linked
twice, and an absent canonical VAT (taxes not seeded) is a silent no-op rather
than aborting the reset.
"""
from typing import Iterable

# The canonical demo VAT — the German standard rate (19%) seeded by
# ``vbwd.services.tax_seeder``. The single source of truth for "the tax demo
# sellables carry"; not a separate placeholder code (DRY).
DEMO_VAT_CODE = "VAT_DE"


def link_demo_tax(session, sellables: Iterable, code: str = DEMO_VAT_CODE) -> int:
    """Link the canonical demo tax (by ``code``) to each sellable, idempotently.

    Args:
        session: Active SQLAlchemy session.
        sellables: Objects exposing the uniform ``taxes`` relationship (plans,
            addons, products, resources, token bundles).
        code: Tax ``code`` to link (defaults to the standard VAT); pass the
            reduced-rate code for variety on a subset of items.

    Returns:
        Number of sellables newly linked (0 when already linked or when the tax
        is absent — both safe no-ops).
    """
    from vbwd.repositories.tax_repository import TaxRepository

    tax = TaxRepository(session).find_by_code(code)
    if tax is None:
        return 0

    linked = 0
    for sellable in sellables:
        if tax not in sellable.taxes:
            sellable.taxes.append(tax)
            linked += 1
    return linked
