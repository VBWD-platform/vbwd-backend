"""Unit tests for the country export / import service (Settings → Countries).

Exercised against the live test DB session (real upsert + commit semantics),
isolating by wiping the country table before and after each test.
"""
import pytest

from vbwd.extensions import db
from vbwd.models.country import Country
from vbwd.services.country_io import (
    EXPORT_KIND,
    EXPORT_VERSION,
    CountryImportError,
    export_countries,
    import_countries,
)


def _wipe_countries(session):
    session.query(Country).delete()
    session.commit()


@pytest.fixture
def session(app):
    with app.app_context():
        _wipe_countries(db.session)
        try:
            yield db.session
        finally:
            db.session.rollback()
            _wipe_countries(db.session)


def _seed(session, code, name, is_enabled, position):
    from uuid import uuid4

    session.add(
        Country(
            id=uuid4(),
            code=code,
            name=name,
            is_enabled=is_enabled,
            position=position,
        )
    )
    session.commit()


class TestExportCountries:
    def test_envelope_shape(self, session):
        _seed(session, "DE", "Germany", True, 0)

        envelope = export_countries(session)

        assert envelope["vbwd_export"] == EXPORT_KIND
        assert envelope["version"] == EXPORT_VERSION
        assert envelope["countries"] == [
            {"code": "DE", "name": "Germany", "is_enabled": True, "position": 0}
        ]

    def test_export_omits_ids_and_timestamps(self, session):
        _seed(session, "DE", "Germany", True, 0)

        row = export_countries(session)["countries"][0]

        assert set(row) == {"code", "name", "is_enabled", "position"}


class TestImportCountries:
    def test_creates_missing(self, session):
        payload = {
            "vbwd_export": "countries",
            "version": 1,
            "countries": [
                {"code": "FR", "name": "France", "is_enabled": True, "position": 1}
            ],
        }

        result = import_countries(session, payload)

        assert result.created == 1
        assert result.updated == 0
        france = session.query(Country).filter_by(code="FR").one()
        assert france.name == "France"
        assert france.is_enabled is True

    def test_updates_existing_by_code(self, session):
        _seed(session, "DE", "Germany", False, 999)

        import_countries(
            session,
            {
                "countries": [
                    {
                        "code": "DE",
                        "name": "Deutschland",
                        "is_enabled": True,
                        "position": 0,
                    }
                ]
            },
        )

        germany = session.query(Country).filter_by(code="DE").one()
        assert germany.name == "Deutschland"
        assert germany.is_enabled is True
        assert germany.position == 0

    def test_round_trip_is_idempotent(self, session):
        _seed(session, "DE", "Germany", True, 0)
        _seed(session, "US", "United States", False, 999)

        envelope = export_countries(session)
        result = import_countries(session, envelope)

        assert result.created == 0
        assert result.updated == 2
        assert session.query(Country).count() == 2

    def test_rejects_non_object_payload(self, session):
        with pytest.raises(CountryImportError):
            import_countries(session, [1, 2, 3])

    def test_rejects_wrong_export_kind(self, session):
        with pytest.raises(CountryImportError):
            import_countries(session, {"vbwd_export": "plans", "countries": []})

    def test_rejects_missing_countries_list(self, session):
        with pytest.raises(CountryImportError):
            import_countries(session, {"vbwd_export": "countries"})

    def test_rejects_row_without_code(self, session):
        with pytest.raises(CountryImportError):
            import_countries(session, {"countries": [{"name": "No Code"}]})
