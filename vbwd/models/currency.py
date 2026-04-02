"""Currency domain model."""
from decimal import Decimal, ROUND_HALF_UP
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class Currency(BaseModel):
    """
    Currency model with exchange rates.

    One currency is marked as default (is_default=True).
    All prices are stored in default currency.
    Other currencies use exchange_rate for conversion.
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
        db.Numeric(10, 6),
        nullable=False,
        default=Decimal("1.0"),
    )  # Rate relative to default currency
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    decimal_places = db.Column(db.Integer, nullable=False, default=2)

    def convert_from_default(self, amount: Decimal) -> Decimal:
        """
        Convert amount from default currency to this currency.

        Args:
            amount: Amount in default currency.

        Returns:
            Amount in this currency, rounded to decimal_places.
        """
        converted = amount * self.exchange_rate
        return converted.quantize(
            Decimal(10) ** -self.decimal_places,
            rounding=ROUND_HALF_UP,
        )

    def convert_to_default(self, amount: Decimal) -> Decimal:
        """
        Convert amount from this currency to default currency.

        Args:
            amount: Amount in this currency.

        Returns:
            Amount in default currency.
        """
        if self.exchange_rate == 0:
            raise ValueError("Exchange rate cannot be zero")
        return (amount / self.exchange_rate).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    def convert_to(self, amount: Decimal, target: "Currency") -> Decimal:
        """
        Convert amount from this currency to target currency.

        Args:
            amount: Amount in this currency.
            target: Target currency.

        Returns:
            Amount in target currency.
        """
        # First convert to default, then to target
        in_default = self.convert_to_default(amount)
        return target.convert_from_default(in_default)

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
            "is_default": self.is_default,
            "is_active": self.is_active,
        }

    def __repr__(self) -> str:
        return f"<Currency(code='{self.code}', rate={self.exchange_rate})>"
