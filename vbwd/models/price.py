"""Price domain model."""
from decimal import Decimal
from typing import Optional
from sqlalchemy.dialects.postgresql import UUID, JSONB
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class Price(BaseModel):
    """
    Price model with currency and tax support.

    Stores pricing information with currency reference and tax breakdown.
    """

    __tablename__ = "vbwd_price"

    # Float representation for quick calculations
    price_float = db.Column(db.Float, nullable=False)

    # Precise decimal representation for financial operations
    price_decimal = db.Column(db.Numeric(10, 2), nullable=False)

    # Currency reference
    currency_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_currency.id"),
        nullable=False,
        index=True,
    )

    # Tax breakdown (stores tax calculations)
    # Structure: {"tax_id": "uuid", "tax_rate": 19.0, "tax_amount": 4.99, "net_amount": 25.00}
    taxes = db.Column(JSONB, default=dict)

    # Gross amount (including taxes)
    gross_amount = db.Column(db.Numeric(10, 2), nullable=False)

    # Net amount (excluding taxes)
    net_amount = db.Column(db.Numeric(10, 2), nullable=False)

    # Description or label
    description = db.Column(db.String(255))

    # Relationships
    currency = db.relationship("Currency", backref="prices", lazy="joined")

    def calculate_taxes(self, tax_rate: Decimal) -> Decimal:
        """
        Calculate tax amount based on net amount.

        Args:
            tax_rate: Tax rate percentage (e.g., 19.0 for 19%)

        Returns:
            Tax amount
        """
        from decimal import ROUND_HALF_UP

        tax = self.net_amount * tax_rate / Decimal("100")
        return tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def update_from_net(self, net_amount: Decimal, tax_rate: Optional[Decimal] = None):
        """
        Update price from net amount and calculate gross.

        Args:
            net_amount: Net amount before tax
            tax_rate: Tax rate percentage (optional)
        """
        self.net_amount = net_amount
        self.price_decimal = net_amount

        if tax_rate:
            tax_amount = self.calculate_taxes(tax_rate)
            self.gross_amount = net_amount + tax_amount
            self.taxes = {
                "tax_rate": float(tax_rate),
                "tax_amount": float(tax_amount),
                "net_amount": float(net_amount),
                "gross_amount": float(self.gross_amount),
            }
        else:
            self.gross_amount = net_amount

        self.price_float = float(self.price_decimal)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "price_float": self.price_float,
            "price_decimal": str(self.price_decimal),
            "currency_id": str(self.currency_id),
            "currency_code": self.currency.code if self.currency else None,
            "currency_symbol": self.currency.symbol if self.currency else None,
            "taxes": self.taxes,
            "gross_amount": str(self.gross_amount),
            "net_amount": str(self.net_amount),
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        currency_code = self.currency.code if self.currency else "???"
        return f"<Price(amount={self.price_decimal}, currency={currency_code})>"
