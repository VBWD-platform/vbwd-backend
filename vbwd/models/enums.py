"""Enumeration types for models."""
import enum


class CaseInsensitiveEnum(enum.Enum):
    """An ``enum.Enum`` whose value lookup tolerates any string casing.

    Canonical member values stay UPPERCASE (the on-disk DB column value
    and the JSON wire contract are unchanged); only the *parse* boundary
    becomes case-insensitive. ``_missing_`` returns an *existing* member,
    so identity and membership semantics are preserved
    (``Cls("active") is Cls.ACTIVE``) — a true Liskov substitute for
    ``enum.Enum``. Unknown values return ``None`` here, which makes the
    enum raise ``ValueError`` exactly as before.
    """

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            normalized_value = value.strip().upper()
            for member in cls:
                if member.value == normalized_value:
                    return member
        return None


class UserStatus(CaseInsensitiveEnum):
    """User account status."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class UserRole(CaseInsensitiveEnum):
    """User role — determines app access level."""

    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    USER = "USER"
    VENDOR = "VENDOR"


class SubscriptionStatus(enum.Enum):
    """Subscription status."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TRIALING = "TRIALING"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class InvoiceStatus(enum.Enum):
    """Invoice status."""

    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class BillingPeriod(enum.Enum):
    """Billing period for tariff plans."""

    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"
    QUARTERLY = "QUARTERLY"
    WEEKLY = "WEEKLY"
    DAILY = "DAILY"
    ONE_TIME = "ONE_TIME"


class UserCaseStatus(enum.Enum):
    """User case status."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class PurchaseStatus(enum.Enum):
    """Token bundle purchase status."""

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class LineItemType(enum.Enum):
    """Invoice line item type."""

    SUBSCRIPTION = "SUBSCRIPTION"
    TOKEN_BUNDLE = "TOKEN_BUNDLE"
    ADD_ON = "ADD_ON"
    CUSTOM = "CUSTOM"


class TokenTransactionType(enum.Enum):
    """Token transaction type."""

    PURCHASE = "PURCHASE"
    USAGE = "USAGE"
    REFUND = "REFUND"
    BONUS = "BONUS"
    ADJUSTMENT = "ADJUSTMENT"
    SUBSCRIPTION = "SUBSCRIPTION"


class AddonSubscriptionStatus(enum.Enum):
    """Addon subscription status."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
