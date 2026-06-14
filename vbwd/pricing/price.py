"""The computed ``Price`` value object (S85.0).

``Price`` is NOT a DB model — it is the full-precision result of a price
calculation, produced by ``PriceFactory``. It carries the net amount, the
per-tax breakdown, the gross amount, and the (global) currency code.

Invariant (enforced by the factory at construction): ::

    netto + sum(tax.amount for tax in taxes) == brutto

No value is ever rounded in code (D4); rounding is a display concern.
"""
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class PriceTax:
    """One applied tax line: its code, human-readable name, rate, and amount."""

    code: str
    name: str
    rate: float
    amount: float

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to ``{"code", "name", "rate", "amount"}``."""
        return {
            "code": self.code,
            "name": self.name,
            "rate": self.rate,
            "amount": self.amount,
        }


@dataclass(frozen=True)
class Price:
    """A computed price: netto + tax breakdown + brutto, in one currency."""

    netto: float
    taxes: List[PriceTax]
    brutto: float
    currency: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to ``{"netto", "taxes": [...], "brutto", "currency"}``."""
        return {
            "netto": self.netto,
            "taxes": [tax.to_dict() for tax in self.taxes],
            "brutto": self.brutto,
            "currency": self.currency,
        }
