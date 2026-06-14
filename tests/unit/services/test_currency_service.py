"""Tests for the settings-sourced CurrencyService (S84).

The service reads the default/active set from the core settings JSON
(injected reader/writer callables) and resolves the rows from the catalog
repository. All conversion math is ``Decimal`` end-to-end.
"""
import pytest
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4


def _currency(code: str, rate: str, decimal_places: int = 2):
    from vbwd.models.currency import Currency

    currency = Currency()
    currency.id = uuid4()
    currency.code = code
    currency.name = code
    currency.symbol = code[0]
    currency.exchange_rate = Decimal(rate)
    currency.decimal_places = decimal_places
    return currency


class _FakeSettings:
    """A minimal settings store double: in-memory reader + writer."""

    def __init__(self, default_currency="EUR", active_currencies=None):
        self.data = {
            "default_currency": default_currency,
            "active_currencies": active_currencies or ["EUR"],
            "cross_rate_base": "default",
        }

    def read(self):
        return dict(self.data)

    def write(self, partial):
        self.data.update(partial)
        return dict(self.data)


def _make_service(catalog, settings):
    """Build a CurrencyService over a stub repo + fake settings."""
    from vbwd.services.currency_service import CurrencyService

    by_code = {c.code: c for c in catalog}
    repo = Mock()
    repo.find_by_code.side_effect = lambda code: by_code.get(code.upper())
    repo.list_all.side_effect = lambda: list(by_code.values())
    repo.update.side_effect = lambda entity: entity

    def _save(entity):
        by_code[entity.code] = entity
        return entity

    def _delete_by_code(code):
        if code.upper() in by_code:
            del by_code[code.upper()]
            return True
        return False

    repo.save.side_effect = _save
    repo.delete_by_code.side_effect = _delete_by_code
    service = CurrencyService(
        currency_repo=repo,
        settings_reader=settings.read,
        settings_writer=settings.write,
    )
    return service, repo


class TestGetDefaultCurrency:
    def test_resolves_default_from_settings(self):
        catalog = [_currency("EUR", "1.0"), _currency("USD", "1.08")]
        settings = _FakeSettings(
            default_currency="USD", active_currencies=["EUR", "USD"]
        )
        service, _ = _make_service(catalog, settings)

        result = service.get_default_currency()

        assert result.code == "USD"

    def test_raises_when_default_absent_from_catalog(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(
            default_currency="USD", active_currencies=["EUR", "USD"]
        )
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.get_default_currency()


class TestGetActiveCurrencies:
    def test_resolves_active_set_from_settings(self):
        catalog = [
            _currency("EUR", "1.0"),
            _currency("USD", "1.08"),
            _currency("GBP", "0.85"),
        ]
        settings = _FakeSettings(
            default_currency="EUR", active_currencies=["EUR", "GBP"]
        )
        service, _ = _make_service(catalog, settings)

        codes = {c.code for c in service.get_active_currencies()}

        assert codes == {"EUR", "GBP"}


class TestSetActive:
    def test_adds_code_to_active_set(self):
        catalog = [_currency("EUR", "1.0"), _currency("USD", "1.08")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        service.set_active("USD", True)

        assert "USD" in settings.data["active_currencies"]

    def test_removes_code_from_active_set(self):
        catalog = [_currency("EUR", "1.0"), _currency("USD", "1.08")]
        settings = _FakeSettings(
            default_currency="EUR", active_currencies=["EUR", "USD"]
        )
        service, _ = _make_service(catalog, settings)

        service.set_active("USD", False)

        assert "USD" not in settings.data["active_currencies"]

    def test_removing_default_raises(self):
        catalog = [_currency("EUR", "1.0"), _currency("USD", "1.08")]
        settings = _FakeSettings(
            default_currency="EUR", active_currencies=["EUR", "USD"]
        )
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.set_active("EUR", False)

    def test_activating_unknown_code_raises(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.set_active("XYZ", True)


class TestSetDefault:
    def test_writes_default_and_rebases_rates(self):
        # EUR default; USD 1.08, GBP 0.85 (per EUR). Switch default → USD.
        eur = _currency("EUR", "1.0")
        usd = _currency("USD", "1.08")
        gbp = _currency("GBP", "0.85")
        catalog = [eur, usd, gbp]
        settings = _FakeSettings(
            default_currency="EUR", active_currencies=["EUR", "USD", "GBP"]
        )
        service, _ = _make_service(catalog, settings)

        service.set_default("USD")

        assert settings.data["default_currency"] == "USD"
        # New default rate is exactly 1.
        assert usd.exchange_rate == Decimal("1")
        # EUR re-based: old 1.0 / old USD 1.08.
        assert abs(eur.exchange_rate - (Decimal("1.0") / Decimal("1.08"))) < Decimal(
            "1e-12"
        )
        # GBP re-based: old 0.85 / old USD 1.08.
        assert abs(gbp.exchange_rate - (Decimal("0.85") / Decimal("1.08"))) < Decimal(
            "1e-12"
        )

    def test_non_active_target_raises(self):
        catalog = [_currency("EUR", "1.0"), _currency("USD", "1.08")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.set_default("USD")

    def test_unknown_target_raises(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.set_default("XYZ")


class TestUpdateExchangeRate:
    def test_updates_non_default_rate(self):
        catalog = [_currency("EUR", "1.0"), _currency("USD", "1.08")]
        settings = _FakeSettings(
            default_currency="EUR", active_currencies=["EUR", "USD"]
        )
        service, _ = _make_service(catalog, settings)

        updated = service.update_exchange_rate("USD", Decimal("1.10"))

        assert updated.exchange_rate == Decimal("1.10")

    def test_default_rate_edit_raises(self):
        catalog = [_currency("EUR", "1.0"), _currency("USD", "1.08")]
        settings = _FakeSettings(
            default_currency="EUR", active_currencies=["EUR", "USD"]
        )
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.update_exchange_rate("EUR", Decimal("2.0"))

    def test_non_positive_rate_raises(self):
        catalog = [_currency("EUR", "1.0"), _currency("USD", "1.08")]
        settings = _FakeSettings(
            default_currency="EUR", active_currencies=["EUR", "USD"]
        )
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.update_exchange_rate("USD", Decimal("0"))

    def test_unknown_code_raises(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.update_exchange_rate("XYZ", Decimal("1.0"))


class TestConvertAccuracy:
    """Conversion accuracy ≤ 1e-7, every base, Decimal-only."""

    TOLERANCE = Decimal("1e-7")

    def _grid_catalog(self):
        # Per-EUR rates (EUR default).
        return [
            _currency("EUR", "1.0"),
            _currency("USD", "1.08"),
            _currency("GBP", "0.85"),
            _currency("JPY", "160.5", decimal_places=0),
        ]

    def _settings(self):
        return _FakeSettings(
            default_currency="EUR",
            active_currencies=["EUR", "USD", "GBP", "JPY"],
        )

    def test_convert_returns_decimal_type(self):
        service, _ = _make_service(self._grid_catalog(), self._settings())
        result = service.convert(Decimal("100"), "GBP", "JPY")
        assert isinstance(result, Decimal)

    def test_convert_matches_hand_computed(self):
        # 100 GBP → JPY (EUR default): 100 / 0.85 * 160.5
        service, _ = _make_service(self._grid_catalog(), self._settings())
        expected = (Decimal("100") / Decimal("0.85")) * Decimal("160.5")
        result = service.convert(Decimal("100"), "GBP", "JPY")
        assert abs(result - expected) <= self.TOLERANCE

    def test_convert_one_default_to_x(self):
        service, _ = _make_service(self._grid_catalog(), self._settings())
        result = service.convert(Decimal("1"), "EUR", "USD")
        assert abs(result - Decimal("1.08")) <= self.TOLERANCE

    def test_round_trip_is_lossless(self):
        service, _ = _make_service(self._grid_catalog(), self._settings())
        for amount in (Decimal("1"), Decimal("37.55"), Decimal("1000.01")):
            for source, target in (("USD", "GBP"), ("GBP", "JPY"), ("EUR", "USD")):
                there = service.convert(amount, source, target)
                back = service.convert(there, target, source)
                assert abs(back - amount) <= self.TOLERANCE

    def test_base_invariance_across_defaults(self):
        # GBP→JPY must be identical whether EUR or USD is the default.
        grid_eur = self._grid_catalog()
        service_eur, _ = _make_service(grid_eur, self._settings())
        before = service_eur.convert(Decimal("100"), "GBP", "JPY")

        # Re-base the SAME numbers to USD default and re-convert.
        grid_usd = self._grid_catalog()
        settings_usd = self._settings()
        service_usd, _ = _make_service(grid_usd, settings_usd)
        service_usd.set_default("USD")
        after = service_usd.convert(Decimal("100"), "GBP", "JPY")

        assert abs(after - before) <= self.TOLERANCE

    def test_base_invariance_non_usd_third_base(self):
        grid_eur = self._grid_catalog()
        service_eur, _ = _make_service(grid_eur, self._settings())
        before = service_eur.convert(Decimal("250"), "USD", "JPY")

        grid_gbp = self._grid_catalog()
        service_gbp, _ = _make_service(grid_gbp, self._settings())
        service_gbp.set_default("GBP")
        after = service_gbp.convert(Decimal("250"), "USD", "JPY")

        assert abs(after - before) <= self.TOLERANCE

    def test_set_default_preserves_all_pairwise_conversions(self):
        pairs = [("USD", "GBP"), ("GBP", "JPY"), ("EUR", "USD"), ("JPY", "EUR")]
        amount = Decimal("123.45")

        grid_before = self._grid_catalog()
        service_before, _ = _make_service(grid_before, self._settings())
        before = {p: service_before.convert(amount, *p) for p in pairs}

        grid_after = self._grid_catalog()
        service_after, _ = _make_service(grid_after, self._settings())
        service_after.set_default("USD")
        for pair in pairs:
            after = service_after.convert(amount, *pair)
            assert abs(after - before[pair]) <= self.TOLERANCE, pair

    def test_float_fragile_rate_stays_exact(self):
        # Rates whose float products drift (0.1 + 0.2). Decimal keeps it exact.
        catalog = [
            _currency("EUR", "1.0"),
            _currency("AAA", "0.1"),
            _currency("BBB", "0.2"),
        ]
        settings = _FakeSettings(
            default_currency="EUR", active_currencies=["EUR", "AAA", "BBB"]
        )
        service, _ = _make_service(catalog, settings)
        # AAA → BBB: amount / 0.1 * 0.2 = amount * 2 exactly.
        result = service.convert(Decimal("3"), "AAA", "BBB")
        assert abs(result - Decimal("6")) <= self.TOLERANCE


class TestConvertSameCurrency:
    def test_same_currency_returns_amount(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, repo = _make_service(catalog, settings)
        result = service.convert(Decimal("100"), "EUR", "EUR")
        assert result == Decimal("100.00")

    def test_unknown_currency_raises(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)
        with pytest.raises(ValueError):
            service.convert(Decimal("100"), "EUR", "XXX")


class TestGetCurrencyByCode:
    def test_returns_currency_uppercased(self):
        catalog = [_currency("USD", "1.08")]
        settings = _FakeSettings(default_currency="USD", active_currencies=["USD"])
        service, repo = _make_service(catalog, settings)
        result = service.get_currency_by_code("usd")
        assert result is not None and result.code == "USD"


class TestCreateCurrency:
    def test_creates_inactive_catalog_row(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, repo = _make_service(catalog, settings)

        created = service.create_currency(
            code="GBP", name="Pound", symbol="£", exchange_rate="0.85"
        )

        assert created.code == "GBP"
        assert created.name == "Pound"
        assert created.symbol == "£"
        assert created.exchange_rate == Decimal("0.85")
        # Inactive by default: NOT added to active_currencies, NOT default.
        assert "GBP" not in settings.data["active_currencies"]
        assert settings.data["default_currency"] == "EUR"
        repo.save.assert_called_once()

    def test_defaults_decimal_places_and_rate(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        created = service.create_currency(code="USD", name="Dollar", symbol="$")

        assert created.decimal_places == 2
        assert created.exchange_rate == Decimal("1.0")

    def test_duplicate_code_raises(self):
        catalog = [_currency("EUR", "1.0"), _currency("USD", "1.08")]
        settings = _FakeSettings(
            default_currency="EUR", active_currencies=["EUR", "USD"]
        )
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.create_currency(code="USD", name="Dollar", symbol="$")

    def test_duplicate_code_case_insensitive_raises(self):
        catalog = [_currency("USD", "1.08")]
        settings = _FakeSettings(default_currency="USD", active_currencies=["USD"])
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.create_currency(code="usd", name="Dollar", symbol="$")

    def test_invalid_code_too_short_raises(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.create_currency(code="US", name="Dollar", symbol="$")

    def test_invalid_code_non_alpha_raises(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.create_currency(code="U5D", name="Dollar", symbol="$")

    def test_non_positive_rate_raises(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.create_currency(
                code="USD", name="Dollar", symbol="$", exchange_rate="0"
            )

    def test_negative_decimal_places_raises(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.create_currency(
                code="USD", name="Dollar", symbol="$", decimal_places=-1
            )


class TestDeleteCurrency:
    def test_deletes_inactive_non_default_row(self):
        catalog = [_currency("EUR", "1.0"), _currency("GBP", "0.85")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, repo = _make_service(catalog, settings)

        service.delete_currency("GBP")

        repo.delete_by_code.assert_called_once()
        assert service.get_currency_by_code("GBP") is None

    def test_unknown_code_raises(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        with pytest.raises(LookupError):
            service.delete_currency("XYZ")

    def test_active_currency_raises(self):
        catalog = [_currency("EUR", "1.0"), _currency("USD", "1.08")]
        settings = _FakeSettings(
            default_currency="EUR", active_currencies=["EUR", "USD"]
        )
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.delete_currency("USD")

    def test_default_currency_raises(self):
        catalog = [_currency("EUR", "1.0")]
        settings = _FakeSettings(default_currency="EUR", active_currencies=["EUR"])
        service, _ = _make_service(catalog, settings)

        with pytest.raises(ValueError):
            service.delete_currency("EUR")
