"""Tax domain models."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Optional
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class Tax(BaseModel):
    """
    Tax configuration model.

    Supports VAT, sales tax, and regional taxes.
    Rates are stored as percentages (e.g., 19.0 for 19%).
    """

    __tablename__ = "vbwd_tax"

    name = db.Column(db.String(100), nullable=False)
    code = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
        index=True,
    )  # e.g., VAT_DE, VAT_FR, SALES_TAX_CA
    description = db.Column(db.Text)
    rate = db.Column(
        db.Numeric(5, 2),
        nullable=False,
    )  # Percentage (19.0 = 19%)
    country_code = db.Column(
        db.String(2),
        index=True,
    )  # ISO 3166-1 alpha-2
    region_code = db.Column(db.String(10))  # State/province code
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_inclusive = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
    )  # True if prices include tax

    # Relationship to historical rates
    historical_rates = db.relationship(
        "TaxRate",
        backref="tax",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def calculate(self, net_amount: Decimal) -> Decimal:
        """
        Calculate tax amount from net amount.

        Args:
            net_amount: Amount before tax.

        Returns:
            Tax amount.
        """
        tax = net_amount * self.rate / Decimal("100")
        return tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_gross(self, net_amount: Decimal) -> Decimal:
        """
        Calculate gross amount (net + tax).

        Args:
            net_amount: Amount before tax.

        Returns:
            Gross amount including tax.
        """
        return net_amount + self.calculate(net_amount)

    def extract_net(self, gross_amount: Decimal) -> Decimal:
        """
        Extract net amount from gross (tax-inclusive) amount.

        Args:
            gross_amount: Amount including tax.

        Returns:
            Net amount before tax.
        """
        divisor = Decimal("1") + (self.rate / Decimal("100"))
        net = gross_amount / divisor
        return net.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def extract_tax(self, gross_amount: Decimal) -> Decimal:
        """
        Extract tax amount from gross amount.

        Args:
            gross_amount: Amount including tax.

        Returns:
            Tax portion of gross amount.
        """
        net = self.extract_net(gross_amount)
        return gross_amount - net

    def is_applicable(
        self,
        country_code: str,
        region_code: Optional[str] = None,
    ) -> bool:
        """
        Check if this tax applies to given location.

        Args:
            country_code: ISO country code.
            region_code: Optional state/region code.

        Returns:
            True if tax applies.
        """
        if self.country_code and self.country_code != country_code:
            return False
        if self.region_code and self.region_code != region_code:
            return False
        return True

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "rate": str(self.rate),
            "country_code": self.country_code,
            "region_code": self.region_code,
            "is_active": self.is_active,
            "is_inclusive": self.is_inclusive,
        }

    def __repr__(self) -> str:
        return f"<Tax(code='{self.code}', rate={self.rate}%)>"


class TaxRate(BaseModel):
    """
    Historical tax rates.

    Tracks rate changes over time for accurate
    invoice recalculation.
    """

    __tablename__ = "vbwd_tax_rate"

    tax_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_tax.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rate = db.Column(db.Numeric(5, 2), nullable=False)
    valid_from = db.Column(db.Date, nullable=False)
    valid_to = db.Column(db.Date)  # NULL means still valid

    def is_valid_on(self, check_date: date) -> bool:
        """Check if rate was valid on given date."""
        if check_date < self.valid_from:
            return False
        if self.valid_to and check_date > self.valid_to:
            return False
        return True

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "tax_id": self.tax_id,
            "rate": str(self.rate),
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
        }
