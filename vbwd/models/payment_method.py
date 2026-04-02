"""PaymentMethod domain model for enterprise payment management."""
from decimal import Decimal
from typing import Optional
from sqlalchemy.dialects.postgresql import UUID, JSON
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class PaymentMethod(BaseModel):
    """
    Payment method model for checkout.

    Defines available payment methods with fees, restrictions, and configuration.
    Similar to enterprise e-commerce platforms (Shopware, OXID, Magento).
    """

    __tablename__ = "vbwd_payment_method"

    # Unique identifier (immutable after creation)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # Display information
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    short_description = db.Column(db.String(255), nullable=True)
    icon = db.Column(db.String(255), nullable=True)

    # Plugin integration
    plugin_id = db.Column(db.String(100), nullable=True)

    # Status and ordering
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    position = db.Column(db.Integer, nullable=False, default=0)

    # Amount restrictions
    min_amount = db.Column(db.Numeric(10, 2), nullable=True)
    max_amount = db.Column(db.Numeric(10, 2), nullable=True)

    # Currency and country restrictions (JSON arrays)
    currencies = db.Column(JSON, nullable=False, default=list)
    countries = db.Column(JSON, nullable=False, default=list)

    # Fee configuration
    fee_type = db.Column(
        db.String(20), nullable=False, default="none"
    )  # 'none', 'fixed', 'percentage'
    fee_amount = db.Column(db.Numeric(10, 4), nullable=True)
    fee_charged_to = db.Column(
        db.String(20), nullable=False, default="customer"
    )  # 'customer' or 'merchant'

    # Non-sensitive configuration (plugin settings, NOT credentials)
    config = db.Column(JSON, nullable=False, default=dict)

    # Instructions for users
    instructions = db.Column(db.Text, nullable=True)

    # Relationships
    translations = db.relationship(
        "PaymentMethodTranslation",
        backref="payment_method",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def calculate_fee(self, amount: Decimal) -> Decimal:
        """
        Calculate the fee for a given amount.

        Args:
            amount: The base amount to calculate fee for

        Returns:
            The calculated fee amount
        """
        if self.fee_type == "none" or self.fee_amount is None:
            return Decimal("0")
        elif self.fee_type == "fixed":
            return Decimal(str(self.fee_amount))
        elif self.fee_type == "percentage":
            return (amount * Decimal(str(self.fee_amount)) / Decimal("100")).quantize(
                Decimal("0.01")
            )
        return Decimal("0")

    def is_available_for_amount(self, amount: Decimal) -> bool:
        """
        Check if this payment method is available for a given amount.

        Args:
            amount: The order amount

        Returns:
            True if available, False otherwise
        """
        if not self.is_active:
            return False

        if self.min_amount is not None and amount < self.min_amount:
            return False

        if self.max_amount is not None and amount > self.max_amount:
            return False

        return True

    def is_available_for_currency(self, currency_code: str) -> bool:
        """
        Check if this payment method is available for a given currency.

        Args:
            currency_code: The currency code (e.g., 'EUR', 'USD')

        Returns:
            True if available (empty list means all currencies)
        """
        if not self.currencies:
            return True
        return currency_code.upper() in [c.upper() for c in self.currencies]

    def is_available_for_country(self, country_code: str) -> bool:
        """
        Check if this payment method is available for a given country.

        Args:
            country_code: The country code (e.g., 'DE', 'US')

        Returns:
            True if available (empty list means all countries)
        """
        if not self.countries:
            return True
        return country_code.upper() in [c.upper() for c in self.countries]

    def is_available(
        self,
        amount: Optional[Decimal] = None,
        currency_code: Optional[str] = None,
        country_code: Optional[str] = None,
    ) -> bool:
        """
        Check if this payment method is available for given parameters.

        Args:
            amount: Order amount (optional)
            currency_code: Currency code (optional)
            country_code: Country code (optional)

        Returns:
            True if available for all provided parameters
        """
        if not self.is_active:
            return False

        if amount is not None and not self.is_available_for_amount(amount):
            return False

        if currency_code is not None and not self.is_available_for_currency(
            currency_code
        ):
            return False

        if country_code is not None and not self.is_available_for_country(country_code):
            return False

        return True

    def get_translation(self, locale: str) -> Optional["PaymentMethodTranslation"]:
        """
        Get translation for a specific locale.

        Args:
            locale: The locale code (e.g., 'de', 'en')

        Returns:
            Translation if found, None otherwise
        """
        return self.translations.filter_by(locale=locale).first()

    def to_dict(self) -> dict:
        """Convert to dictionary (admin view with all fields)."""
        return {
            "id": str(self.id),
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "short_description": self.short_description,
            "icon": self.icon,
            "plugin_id": self.plugin_id,
            "is_active": self.is_active,
            "is_default": self.is_default,
            "position": self.position,
            "min_amount": str(self.min_amount) if self.min_amount else None,
            "max_amount": str(self.max_amount) if self.max_amount else None,
            "currencies": self.currencies or [],
            "countries": self.countries or [],
            "fee_type": self.fee_type,
            "fee_amount": str(self.fee_amount) if self.fee_amount else None,
            "fee_charged_to": self.fee_charged_to,
            "config": self.config or {},
            "instructions": self.instructions,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_public_dict(self, locale: Optional[str] = None) -> dict:
        """
        Convert to dictionary for public/checkout view.

        Excludes sensitive fields like config.
        Applies translation if locale provided.
        """
        # Get translation if available
        name = self.name
        description = self.description
        short_description = self.short_description
        instructions = self.instructions

        if locale:
            translation = self.get_translation(locale)
            if translation:
                name = translation.name or name
                description = translation.description or description
                short_description = translation.short_description or short_description
                instructions = translation.instructions or instructions

        return {
            "id": str(self.id),
            "code": self.code,
            "name": name,
            "description": description,
            "short_description": short_description,
            "icon": self.icon,
            "is_active": self.is_active,
            "is_default": self.is_default,
            "position": self.position,
            "fee_type": self.fee_type,
            "fee_amount": str(self.fee_amount) if self.fee_amount else None,
            "fee_charged_to": self.fee_charged_to,
            "instructions": instructions,
        }

    def __repr__(self) -> str:
        return f"<PaymentMethod(code='{self.code}', name='{self.name}')>"


class PaymentMethodTranslation(db.Model):  # type: ignore[name-defined]
    """
    Translation model for payment methods.

    Supports i18n by providing localized names and descriptions.
    """

    __tablename__ = "vbwd_payment_method_translation"

    id = db.Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=db.text("gen_random_uuid()"),
    )
    payment_method_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_payment_method.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    locale = db.Column(db.String(10), nullable=False)  # e.g., 'de', 'en', 'fr'

    # Translated fields
    name = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text, nullable=True)
    short_description = db.Column(db.String(255), nullable=True)
    instructions = db.Column(db.Text, nullable=True)

    # Unique constraint: one translation per locale per payment method
    __table_args__ = (
        db.UniqueConstraint(
            "payment_method_id", "locale", name="uq_payment_method_translation_locale"
        ),
    )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "payment_method_id": str(self.payment_method_id),
            "locale": self.locale,
            "name": self.name,
            "description": self.description,
            "short_description": self.short_description,
            "instructions": self.instructions,
        }

    def __repr__(self) -> str:
        return f"<PaymentMethodTranslation(locale='{self.locale}')>"
