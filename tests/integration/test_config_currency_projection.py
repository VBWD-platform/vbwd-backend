"""S99.0b — GET /api/v1/config publishes the S84 currency projection.

The view-only display switcher needs the active currency set + their cross-rates,
which today live only behind the admin S84 routes. The public config read now
also returns ``base_currency``, ``active_currencies``, and ``currency_rates``
(per active currency → its ``exchange_rate`` to base from ``vbwd_currency``).

This is a read-only projection of the existing data: no auth, no new storage.
Deactivating a currency drops it from the public set. The settings + catalog are
restored at the end so the shared test state is unchanged.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from vbwd.services.core_settings_store import update_core_settings


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    """Live DB session bound to the running app context (real test DB).

    Core integration tests have no shared ``db`` fixture (most use live HTTP);
    this currency projection needs to write catalog rows + read them back
    through the route, so it opens an app context over the real database.
    """
    from vbwd.extensions import db as _db

    with app.app_context():
        yield _db
        _db.session.rollback()


def _ensure_currency(db, code, *, rate, symbol):
    from vbwd.models.currency import Currency
    from vbwd.repositories.currency_repository import CurrencyRepository

    repo = CurrencyRepository(db.session)
    currency = repo.find_by_code(code)
    if currency is None:
        db.session.add(
            Currency(
                id=uuid4(),
                code=code,
                name=code,
                symbol=symbol,
                exchange_rate=Decimal(rate),
                decimal_places=2,
            )
        )
    else:
        currency.exchange_rate = Decimal(rate)
    db.session.commit()


def test_config_publishes_base_active_and_rates(db, client):
    _ensure_currency(db, "EUR", rate="1.0", symbol="€")
    _ensure_currency(db, "USD", rate="1.10", symbol="$")
    update_core_settings({"active_currencies": ["EUR", "USD"]})
    update_core_settings({"default_currency": "EUR"})
    try:
        response = client.get("/api/v1/config")
        assert response.status_code == 200
        body = response.get_json()

        # Existing keys unchanged.
        assert body["default_currency"] == "EUR"
        assert "prices_display_mode" in body
        assert "prices_mode_in_db" in body

        # New S99.0b projection.
        assert body["base_currency"] == "EUR"
        assert set(body["active_currencies"]) == {"EUR", "USD"}
        assert Decimal(body["currency_rates"]["EUR"]) == Decimal("1.0")
        assert Decimal(body["currency_rates"]["USD"]) == Decimal("1.10")
    finally:
        update_core_settings({"default_currency": "EUR"})
        update_core_settings({"active_currencies": ["EUR"]})


def test_deactivating_currency_drops_it_from_public_set(db, client):
    _ensure_currency(db, "EUR", rate="1.0", symbol="€")
    _ensure_currency(db, "USD", rate="1.10", symbol="$")
    update_core_settings({"active_currencies": ["EUR", "USD"]})
    update_core_settings({"default_currency": "EUR"})
    try:
        before = client.get("/api/v1/config").get_json()
        assert "USD" in before["active_currencies"]
        assert "USD" in before["currency_rates"]

        # Deactivate USD (the non-default).
        update_core_settings({"active_currencies": ["EUR"]})

        after = client.get("/api/v1/config").get_json()
        assert "USD" not in after["active_currencies"]
        assert "USD" not in after["currency_rates"]
        assert after["active_currencies"] == ["EUR"]
    finally:
        update_core_settings({"default_currency": "EUR"})
        update_core_settings({"active_currencies": ["EUR"]})


def test_config_currency_projection_requires_no_auth(db, client):
    _ensure_currency(db, "EUR", rate="1.0", symbol="€")
    update_core_settings({"active_currencies": ["EUR"]})
    update_core_settings({"default_currency": "EUR"})
    # No Authorization header — a public read must still succeed.
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    assert "currency_rates" in response.get_json()
