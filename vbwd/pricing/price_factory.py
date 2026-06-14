"""The single price-math entry point (S85.0, D1).

``PriceFactory.get_price_from_object(priceable)`` turns any ``Priceable`` into a
computed ``Price``. It reads the global ``prices_mode_in_db`` setting to know
how to interpret the stored ``raw_price`` (net vs gross), applies the linked
taxes, and resolves the currency once from ``CurrencyService``.

No rounding happens here (D4): the math may use ``Decimal`` internally for
correctness, but the result is cast back to ``float`` without quantizing.
Rounding is a display concern handled in the frontend.
"""
from decimal import Decimal
from typing import Any, Callable, Dict, List

from vbwd.pricing.price import Price, PriceTax
from vbwd.pricing.priceable import Priceable
from vbwd.services.core_settings_store import PRICES_MODE_IN_DB_KEY
from vbwd.services.currency_service import CurrencyService

SettingsReader = Callable[[], Dict[str, Any]]

_NETTO_MODE = "NETTO"
_BRUTTO_MODE = "BRUTTO"
_PERCENT = Decimal("100")


class PriceFactory:
    """Compute a ``Price`` from a ``Priceable`` per the global storage mode.

    Depends only on the core settings reader and ``CurrencyService`` (D1) —
    no plugin model is imported.
    """

    def __init__(
        self,
        settings_reader: SettingsReader,
        currency_service: CurrencyService,
    ):
        """Initialize PriceFactory.

        Args:
            settings_reader: Callable returning the core settings dict (the
                single source of truth for ``prices_mode_in_db``).
            currency_service: Resolves the global default currency.
        """
        self._read_settings = settings_reader
        self._currency_service = currency_service

    def get_price_from_object(self, priceable: Priceable) -> Price:
        """Compute the netto / tax breakdown / brutto for a sellable.

        Args:
            priceable: Any object exposing ``raw_price`` and ``taxes``.

        Returns:
            A full-precision ``Price`` (never rounded).
        """
        storage_mode = self._read_settings().get(PRICES_MODE_IN_DB_KEY, _NETTO_MODE)
        currency_code = self._currency_service.get_default_currency().code

        raw_amount = Decimal(str(priceable.raw_price))
        tax_rates = [Decimal(str(tax.rate)) for tax in priceable.taxes]

        if storage_mode == _BRUTTO_MODE:
            netto = self._netto_from_brutto(raw_amount, tax_rates)
            brutto = raw_amount
        else:
            netto = raw_amount
            brutto = self._brutto_from_netto(raw_amount, tax_rates)

        price_taxes: List[PriceTax] = [
            PriceTax(
                code=tax.code,
                name=getattr(tax, "name", tax.code),
                rate=float(tax.rate),
                amount=float(netto * Decimal(str(tax.rate)) / _PERCENT),
            )
            for tax in priceable.taxes
        ]

        return Price(
            netto=float(netto),
            taxes=price_taxes,
            brutto=float(brutto),
            currency=currency_code,
        )

    @staticmethod
    def _brutto_from_netto(netto: Decimal, tax_rates: List[Decimal]) -> Decimal:
        """NETTO mode: brutto = netto + Σ (netto · rate_i / 100)."""
        total_tax = sum(
            (netto * rate / _PERCENT for rate in tax_rates),
            Decimal("0"),
        )
        return netto + total_tax

    @staticmethod
    def _netto_from_brutto(brutto: Decimal, tax_rates: List[Decimal]) -> Decimal:
        """BRUTTO mode: netto = brutto / (1 + Σ rate_i / 100)."""
        combined_rate = sum(
            (rate / _PERCENT for rate in tax_rates),
            Decimal("0"),
        )
        return brutto / (Decimal("1") + combined_rate)
