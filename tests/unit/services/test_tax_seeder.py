"""Unit tests for the core German VAT tax seeder.

German VAT taxes are foundational billing reference data, seeded by default
on every instance (ungated, like the country catalog).

The shared test DB may already hold the German VAT rows (and they may be
FK-referenced by sellables), so the DB-backed tests do NOT wipe the table.
Instead they assert the seeder's invariants relative to whatever is already
present: the catalog ends fully seeded, a re-run is a no-op, and
pre-existing/edited rows are left untouched. The create-path field mapping is
proven in isolation with a MagicMock session (empty store), avoiding any
dependence on the shared DB's pre-seeded rows.
"""
from decimal import Decimal

import pytest

from vbwd.extensions import db
from vbwd.models.tax import Tax
from vbwd.services.tax_seeder import (
    TAXES,
    TaxSeedResult,
    seed_taxes,
)

# Codes owned by the German VAT seeder.
SEEDED_CODES = [entry.code for entry in TAXES]


@pytest.fixture
def session(app):
    """Live test-DB session inside an app context.

    Ensures the catalog is fully present at teardown so the shared DB is left
    in the same (fully-seeded) state regardless of test order.
    """
    with app.app_context():
        try:
            yield db.session
        finally:
            db.session.rollback()
            seed_taxes(db.session)


def _missing_codes(session):
    """Catalog codes not yet present in the DB."""
    present = {
        row.code for row in session.query(Tax).filter(Tax.code.in_(SEEDED_CODES)).all()
    }
    return [code for code in SEEDED_CODES if code not in present]


class TestSeedTaxes:
    def test_catalog_defines_exactly_two_german_vat_taxes(self):
        assert len(TAXES) == 2
        assert SEEDED_CODES == ["VAT_DE", "VAT_DE_7"]

    def test_seed_creates_only_the_missing_codes(self, session):
        expected_created = len(_missing_codes(session))

        result = seed_taxes(session)

        assert isinstance(result, TaxSeedResult)
        assert result.taxes_created == expected_created
        # Whole catalog is present afterwards.
        assert _missing_codes(session) == []

    def test_catalog_standard_vat_values(self):
        entry = next(item for item in TAXES if item.code == "VAT_DE")

        assert entry.name == "VAT Germany (19%)"
        assert entry.rate == Decimal("19.00")
        assert entry.country_code == "DE"
        assert entry.tax_class == "standard"
        assert entry.is_active is True
        assert entry.is_inclusive is False

    def test_catalog_reduced_vat_values(self):
        entry = next(item for item in TAXES if item.code == "VAT_DE_7")

        assert entry.name == "VAT Germany (7%)"
        assert entry.rate == Decimal("7.00")
        assert entry.country_code == "DE"
        assert entry.tax_class == "reduced"
        assert entry.is_active is True
        assert entry.is_inclusive is False

    def test_seed_writes_catalog_values_on_the_create_path(self):
        # Pure-create path against an empty store (MagicMock) — proves the
        # seeder maps every catalog field onto the persisted Tax faithfully,
        # without depending on the shared DB's pre-seeded rows.
        from unittest.mock import MagicMock

        fake_session = MagicMock()
        fake_session.query.return_value.filter_by.return_value.first.return_value = None
        added = []
        fake_session.add.side_effect = added.append

        result = seed_taxes(fake_session)

        assert result.taxes_created == len(TAXES)
        assert len(added) == len(TAXES)
        by_code = {tax.code: tax for tax in added}
        for entry in TAXES:
            created = by_code[entry.code]
            assert created.name == entry.name
            assert created.rate == entry.rate
            assert created.country_code == entry.country_code
            assert created.tax_class == entry.tax_class
            assert created.is_active is entry.is_active
            assert created.is_inclusive is entry.is_inclusive
        fake_session.commit.assert_called_once()

    def test_idempotent_rerun_creates_nothing(self, session):
        # Guarantee the catalog is present, then a re-run must be a no-op.
        seed_taxes(session)

        result = seed_taxes(session)

        assert result.taxes_created == 0

    def test_operator_edit_survives_rerun(self, session):
        seed_taxes(session)

        # An operator deactivates the reduced VAT and edits its name.
        tax = session.query(Tax).filter_by(code="VAT_DE_7").one()
        original_name = tax.name
        tax.is_active = False
        tax.name = "Reduced (operator edited)"
        session.commit()

        try:
            result = seed_taxes(session)

            assert result.taxes_created == 0
            reloaded = session.query(Tax).filter_by(code="VAT_DE_7").one()
            assert reloaded.is_active is False
            assert reloaded.name == "Reduced (operator edited)"
        finally:
            # Restore so the shared DB is not left with the operator edit.
            restored = session.query(Tax).filter_by(code="VAT_DE_7").one()
            restored.is_active = True
            restored.name = original_name
            session.commit()
