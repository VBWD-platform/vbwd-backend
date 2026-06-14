"""Currency service implementation (settings-sourced — S84).

The *active set* and the *default* currency live in the core settings JSON
(injected reader/writer callables); the ``vbwd_currency`` table is the
catalog + per-default rates only. All conversion math is ``Decimal``
end-to-end so accuracy never drifts (the ≤1e-7 guarantee).
"""
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from vbwd.models.currency import Currency
from vbwd.repositories.currency_repository import CurrencyRepository

SettingsReader = Callable[[], Dict[str, Any]]
SettingsWriter = Callable[[Dict[str, Any]], Dict[str, Any]]

_DEFAULT_CURRENCY_KEY = "default_currency"
_ACTIVE_CURRENCIES_KEY = "active_currencies"
_REBASED_DEFAULT_RATE = Decimal("1")
_ISO_CODE_LENGTH = 3
_DEFAULT_DECIMAL_PLACES = 2
_DEFAULT_EXCHANGE_RATE = "1.0"


class CurrencyService:
    """Currency management — conversion, the active set, and the default.

    Reads/writes the active set + default through the injected settings
    callables (the single source of truth); resolves the rows from the
    catalog repository.
    """

    def __init__(
        self,
        currency_repo: CurrencyRepository,
        settings_reader: SettingsReader,
        settings_writer: SettingsWriter,
    ):
        """Initialize CurrencyService.

        Args:
            currency_repo: Repository for the currency catalog + rates.
            settings_reader: Callable returning the core settings dict.
            settings_writer: Callable persisting a partial settings update and
                returning the merged settings dict.
        """
        self._currency_repo = currency_repo
        self._read_settings = settings_reader
        self._write_settings = settings_writer

    # ── Settings-derived views ────────────────────────────────────────────

    def get_default_currency(self) -> Currency:
        """Resolve the default currency from settings against the catalog.

        Raises:
            ValueError: If the configured default is not in the catalog.
        """
        code = self._read_settings().get(_DEFAULT_CURRENCY_KEY)
        currency = self._currency_repo.find_by_code(code) if code else None
        if not currency:
            raise ValueError(f"Default currency not found in catalog: {code}")
        return currency

    def get_active_currencies(self) -> List[Currency]:
        """Resolve the active set from settings against the catalog.

        Returns the catalog rows whose code is in ``active_currencies`` (codes
        with no catalog row are skipped).
        """
        active_codes = self._read_settings().get(_ACTIVE_CURRENCIES_KEY, [])
        resolved: List[Currency] = []
        for code in active_codes:
            currency = self._currency_repo.find_by_code(code)
            if currency:
                resolved.append(currency)
        return resolved

    def get_currency_by_code(self, code: str) -> Optional[Currency]:
        """Get a catalog currency by ISO code (case-insensitive)."""
        return self._currency_repo.find_by_code(code.upper())

    def get_catalog_view(self) -> List[Dict[str, Any]]:
        """Return every catalog row with ``is_active``/``is_default`` derived.

        The flags come from the settings (the single source of truth), not from
        columns. Rows are ordered active-first, then by code.
        """
        settings = self._read_settings()
        active_codes = set(settings.get(_ACTIVE_CURRENCIES_KEY, []))
        default_code = settings.get(_DEFAULT_CURRENCY_KEY)

        rows: List[Dict[str, Any]] = []
        for currency in self._currency_repo.list_all():
            entry = currency.to_dict()
            entry["is_active"] = currency.code in active_codes
            entry["is_default"] = currency.code == default_code
            rows.append(entry)

        rows.sort(key=lambda row: (not row["is_active"], row["code"]))
        return rows

    # ── Catalog mutations (create / delete) ───────────────────────────────

    def create_currency(
        self,
        code: str,
        name: str,
        symbol: str,
        decimal_places: int = _DEFAULT_DECIMAL_PLACES,
        exchange_rate: str = _DEFAULT_EXCHANGE_RATE,
    ) -> Currency:
        """Add a new catalog row (inactive — not active, not default).

        The new currency is NOT added to the active set and does NOT become
        the default; the admin activates it separately.

        Args:
            code: 3-letter uppercase ISO-style code (validated).
            name: Display name.
            symbol: Display symbol.
            decimal_places: Number of decimal places (≥ 0).
            exchange_rate: Rate per default currency (> 0).

        Returns:
            The created Currency.

        Raises:
            ValueError: If the code is malformed, already in the catalog, the
                rate is ≤ 0, or decimal_places is negative.
        """
        normalized = code.upper() if code else ""
        if (
            len(normalized) != _ISO_CODE_LENGTH
            or not normalized.isalpha()
            or not normalized.isascii()
        ):
            raise ValueError("Currency code must be a 3-letter ISO code: " f"{code!r}")

        if self._currency_repo.find_by_code(normalized):
            raise ValueError(f"Currency already exists: {normalized}")

        if decimal_places < 0:
            raise ValueError("decimal_places must be zero or greater")

        rate_value = Decimal(exchange_rate)
        if rate_value <= 0:
            raise ValueError("Exchange rate must be greater than zero")

        currency = Currency(
            code=normalized,
            name=name,
            symbol=symbol,
            exchange_rate=rate_value,
            decimal_places=decimal_places,
        )
        return self._currency_repo.save(currency)

    def delete_currency(self, code: str) -> None:
        """Remove a catalog row (only inactive, non-default rows are deletable).

        Args:
            code: ISO code of the currency to delete.

        Raises:
            LookupError: If no catalog row matches the code.
            ValueError: If the currency is active or is the default.
        """
        normalized = code.upper()
        currency = self._currency_repo.find_by_code(normalized)
        if not currency:
            raise LookupError(f"Currency not found: {normalized}")

        settings = self._read_settings()
        active_codes = settings.get(_ACTIVE_CURRENCIES_KEY, [])
        default_code = settings.get(_DEFAULT_CURRENCY_KEY)

        if normalized == default_code:
            raise ValueError("Cannot delete the default currency")
        if normalized in active_codes:
            raise ValueError("Cannot delete an active currency")

        self._currency_repo.delete_by_code(normalized)

    # ── Mutations on the active set / default ─────────────────────────────

    def set_active(self, code: str, active: bool) -> List[str]:
        """Add or remove ``code`` in the active set (settings write).

        Returns the new active-code list.

        Raises:
            ValueError: If ``code`` is unknown, or if removing the default.
        """
        normalized = code.upper()
        if not self._currency_repo.find_by_code(normalized):
            raise ValueError(f"Currency not found: {normalized}")

        settings = self._read_settings()
        active_codes = list(settings.get(_ACTIVE_CURRENCIES_KEY, []))
        default_code = settings.get(_DEFAULT_CURRENCY_KEY)

        if active:
            if normalized not in active_codes:
                active_codes.append(normalized)
        else:
            if normalized == default_code:
                raise ValueError("Cannot deactivate the default currency")
            active_codes = [c for c in active_codes if c != normalized]

        merged = self._write_settings({_ACTIVE_CURRENCIES_KEY: active_codes})
        return merged.get(_ACTIVE_CURRENCIES_KEY, active_codes)

    def set_default(self, code: str) -> Currency:
        """Make ``code`` the default and re-base every catalog rate (D3).

        Writes ``settings.default_currency = code``, sets that row's rate to
        ``1``, and re-bases every other row: ``new_X = old_X / old_rate_code``
        (full ``Decimal`` precision, behaviour-preserving). Only an *active*
        currency may become default.

        Raises:
            ValueError: If ``code`` is unknown or not in the active set.
        """
        normalized = code.upper()
        new_default = self._currency_repo.find_by_code(normalized)
        if not new_default:
            raise ValueError(f"Currency not found: {normalized}")

        active_codes = self._read_settings().get(_ACTIVE_CURRENCIES_KEY, [])
        if normalized not in active_codes:
            raise ValueError(
                f"Only an active currency can become default: {normalized}"
            )

        old_default_rate = Decimal(new_default.exchange_rate)
        if old_default_rate == 0:
            raise ValueError("New default currency has a zero exchange rate")

        for currency in self._currency_repo.list_all():
            if currency.code == normalized:
                currency.exchange_rate = _REBASED_DEFAULT_RATE
            else:
                currency.exchange_rate = (
                    Decimal(currency.exchange_rate) / old_default_rate
                )
            self._currency_repo.update(currency)

        self._write_settings({_DEFAULT_CURRENCY_KEY: normalized})
        return new_default

    def update_exchange_rate(self, code: str, rate: Decimal) -> Currency:
        """Update a currency's exchange rate (catalog write).

        Raises:
            ValueError: If the currency is unknown, is the default, or the
                rate is ≤ 0.
        """
        normalized = code.upper()
        currency = self._currency_repo.find_by_code(normalized)
        if not currency:
            raise ValueError(f"Currency not found: {normalized}")

        default_code = self._read_settings().get(_DEFAULT_CURRENCY_KEY)
        if normalized == default_code:
            raise ValueError("Cannot change exchange rate of default currency")

        rate_value = Decimal(rate)
        if rate_value <= 0:
            raise ValueError("Exchange rate must be greater than zero")

        currency.exchange_rate = rate_value
        return self._currency_repo.update(currency)

    # ── Conversion (Decimal-only, full precision) ─────────────────────────

    def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
    ) -> Decimal:
        """
        Convert ``amount`` between currencies, crossing via the default.

        Full ``Decimal`` precision (no intermediate rounding) so the cross is
        lossless and round-trippable to ≤1e-7. Callers round at the display
        boundary.

        Raises:
            ValueError: If either currency code is unknown.
        """
        if from_currency == to_currency:
            return Decimal(amount)

        source = self._currency_repo.find_by_code(from_currency)
        target = self._currency_repo.find_by_code(to_currency)
        if not source or not target:
            raise ValueError(f"Unknown currency: {from_currency} or {to_currency}")

        in_default = source.convert_to_default(Decimal(amount))
        return target.convert_from_default(in_default)
