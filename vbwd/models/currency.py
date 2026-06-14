"""Currency domain model."""
from decimal import Decimal, ROUND_HALF_UP
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class Currency(BaseModel):
    """
    Currency catalog row with an exchange rate.

    ``exchange_rate`` is units of THIS currency per 1 unit of the default
    currency (the default's own rate is ``1.0``). The *active set* and the
    *default* currency are NOT columns — they live in the core settings JSON
    (the single source of truth, S84). This table is catalog + rates only.
    """

    __tablename__ = "vbwd_currency"

    code = db.Column(
        db.String(3),
        unique=True,
        nullable=False,
        index=True,
    )  # ISO 4217 code (EUR, USD, GBP)
    name = db.Column(db.String(100), nullable=False)
    symbol = db.Column(db.String(10), nullable=False)
    exchange_rate = db.Column(
        db.Numeric(18, 8),
        nullable=False,
        default=Decimal("1.0"),
    )  # Rate relative to default currency (units of this currency per default)
    decimal_places = db.Column(db.Integer, nullable=False, default=2)

    def convert_from_default(self, amount: Decimal) -> Decimal:
        """
        Convert amount from default currency to this currency.

        Full-precision ``Decimal`` multiply — NO intermediate rounding, so a
        cross (default → this → other) keeps the ≤1e-7 accuracy guarantee.
        Callers round at the display/storage boundary (``format`` / a final
        ``quantize``), not here.

        Args:
            amount: Amount in default currency.

        Returns:
            Amount in this currency (un-rounded ``Decimal``).
        """
        return amount * self.exchange_rate

    def convert_to_default(self, amount: Decimal) -> Decimal:
        """
        Convert amount from this currency to default currency.

        Full-precision ``Decimal`` divide — NO intermediate rounding.

        Args:
            amount: Amount in this currency.

        Returns:
            Amount in default currency (un-rounded ``Decimal``).
        """
        if self.exchange_rate == 0:
            raise ValueError("Exchange rate cannot be zero")
        return amount / self.exchange_rate

    def convert_to(self, amount: Decimal, target: "Currency") -> Decimal:
        """
        Convert amount from this currency to target currency.

        Crosses via the default at full ``Decimal`` precision and rounds the
        result to the *target's* ``decimal_places`` once, at the end.

        Args:
            amount: Amount in this currency.
            target: Target currency.

        Returns:
            Amount in target currency, rounded to target.decimal_places.
        """
        in_default = self.convert_to_default(amount)
        converted = target.convert_from_default(in_default)
        return converted.quantize(
            Decimal(10) ** -target.decimal_places,
            rounding=ROUND_HALF_UP,
        )

    def format(self, amount: Decimal) -> str:
        """
        Format amount with currency symbol.

        Args:
            amount: Amount to format.

        Returns:
            Formatted string with symbol.
        """
        formatted_amount = f"{amount:.{self.decimal_places}f}"
        return f"{self.symbol}{formatted_amount}"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "symbol": self.symbol,
            "exchange_rate": str(self.exchange_rate),
            "decimal_places": self.decimal_places,
        }

    def __repr__(self) -> str:
        return f"<Currency(code='{self.code}', rate={self.exchange_rate})>"
