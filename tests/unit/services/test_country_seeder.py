"""Unit tests for the core country seeder — Sprint S39 §8b.

Countries are foundational billing-address reference data, seeded by
default on every instance (ungated, like the RBAC roles). These tests
exercise ``seed_countries`` against the live test DB session (real
SQLAlchemy upsert + commit semantics, which a MagicMock cannot model),
isolating by wiping the country table before and after each test.
"""
import pytest

from vbwd.extensions import db
from vbwd.models.country import Country
from vbwd.services.country_seeder import (
    COUNTRIES,
    ENABLED_CODES,
    CountrySeedResult,
    seed_countries,
)

# DACH must always be enabled by default.
DACH_CODES = {"DE", "AT", "CH"}


def _wipe_countries(session):
    """Remove all country rows so each test starts clean."""
    session.query(Country).delete()
    session.commit()


@pytest.fixture
def session(app):
    """Live test-DB session inside an app context, countries wiped clean."""
    with app.app_context():
        _wipe_countries(db.session)
        try:
            yield db.session
        finally:
            db.session.rollback()
            _wipe_countries(db.session)


class TestSeedCountries:
    def test_seeds_all_countries(self, session):
        result = seed_countries(session)

        assert isinstance(result, CountrySeedResult)
        assert session.query(Country).count() == len(COUNTRIES)
        assert result.created == len(COUNTRIES)

    def test_dach_countries_enabled(self, session):
        seed_countries(session)

        for code in DACH_CODES:
            country = session.query(Country).filter_by(code=code).one()
            assert country.is_enabled is True

    def test_non_dach_default_disabled_except_enabled_codes(self, session):
        seed_countries(session)

        for country in session.query(Country).all():
            expected = country.code in ENABLED_CODES
            assert country.is_enabled is expected
        assert DACH_CODES.issubset(ENABLED_CODES)

    def test_enabled_count_matches_enabled_codes(self, session):
        result = seed_countries(session)

        assert result.enabled_count == len(ENABLED_CODES)
        enabled = session.query(Country).filter_by(is_enabled=True).count()
        assert enabled == len(ENABLED_CODES)

    def test_idempotent_rerun_creates_nothing(self, session):
        seed_countries(session)
        result = seed_countries(session)

        assert result.created == 0
        assert session.query(Country).count() == len(COUNTRIES)


class TestSeederIsSingleSource:
    """install_demo_data.py must delegate, not duplicate the list (DRY)."""

    def test_install_demo_data_has_no_inline_country_list(self):
        from pathlib import Path

        source = Path(__file__).resolve().parents[3] / "bin" / "install_demo_data.py"
        text = source.read_text(encoding="utf-8")
        # The inline list/loop is gone — the demo script imports the shared seeder.
        assert "COUNTRIES = [" not in text
        assert "ENABLED_CODES = {" not in text
        assert "from vbwd.services.country_seeder import seed_countries" in text
