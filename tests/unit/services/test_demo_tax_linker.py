"""Unit specs for the core demo-tax linker (S85.4).

The linker is the single source of truth for the canonical demo VAT code and
the idempotent "link this tax to these sellables" operation. Both the core
token-bundle seeder and every plugin catalog seeder use it (DRY); plugins look
the tax up by code through this core service, so no plugin imports another
plugin's models.
"""
from unittest.mock import MagicMock

from vbwd.services import demo_tax_linker


def test_canonical_demo_vat_code_is_the_seeded_standard_vat():
    """The canonical demo VAT code matches a code seeded by ``seed_taxes`` so a
    fresh reset always finds it (no orphan ``VAT_STD`` placeholder)."""
    from vbwd.services.tax_seeder import TAXES

    seeded_codes = {entry.code for entry in TAXES}
    assert demo_tax_linker.DEMO_VAT_CODE in seeded_codes


def test_link_demo_tax_links_canonical_vat_to_each_sellable():
    """Each sellable gains the canonical VAT in its ``taxes`` relationship."""
    session = MagicMock()
    vat = MagicMock(code=demo_tax_linker.DEMO_VAT_CODE)
    session.query.return_value.filter_by.return_value.first.return_value = vat

    sellables = [MagicMock(taxes=[]), MagicMock(taxes=[])]
    linked = demo_tax_linker.link_demo_tax(session, sellables)

    assert linked == 2
    for sellable in sellables:
        assert vat in sellable.taxes


def test_link_demo_tax_is_idempotent():
    """A sellable that already carries the canonical VAT is not linked twice."""
    session = MagicMock()
    vat = MagicMock(code=demo_tax_linker.DEMO_VAT_CODE)
    session.query.return_value.filter_by.return_value.first.return_value = vat

    already = MagicMock(taxes=[vat])
    linked = demo_tax_linker.link_demo_tax(session, [already])

    assert linked == 0
    assert already.taxes == [vat]


def test_link_demo_tax_noop_when_tax_missing():
    """When the canonical VAT is absent (taxes not seeded) the linker is a
    silent no-op rather than crashing the reset."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    sellable = MagicMock(taxes=[])
    linked = demo_tax_linker.link_demo_tax(session, [sellable])

    assert linked == 0
    assert sellable.taxes == []


def test_link_demo_tax_accepts_explicit_code():
    """An explicit ``code`` (e.g. the reduced rate) overrides the default."""
    session = MagicMock()
    reduced = MagicMock(code="VAT_DE_7")
    session.query.return_value.filter_by.return_value.first.return_value = reduced

    sellable = MagicMock(taxes=[])
    demo_tax_linker.link_demo_tax(session, [sellable], code="VAT_DE_7")

    session.query.return_value.filter_by.assert_called_with(code="VAT_DE_7")
    assert reduced in sellable.taxes
