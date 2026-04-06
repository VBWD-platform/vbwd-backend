"""Domain models package."""
from vbwd.models.user import User
from vbwd.models.user_details import UserDetails
from vbwd.models.user_case import UserCase
from vbwd.models.currency import Currency
from vbwd.models.tax import TaxClass, Tax, TaxRate
from vbwd.models.price import Price
from vbwd.models.tarif_plan import TarifPlan
from vbwd.models.subscription import Subscription
from vbwd.models.invoice import UserInvoice
from vbwd.models.invoice_line_item import InvoiceLineItem
from vbwd.models.password_reset_token import PasswordResetToken
from vbwd.models.role import Role, Permission, role_permissions, user_roles
from vbwd.models.user_access_level import (
    UserAccessLevel,
    user_access_level_permissions,
    user_user_access_levels,
)
from vbwd.models.feature_usage import FeatureUsage
from vbwd.models.token_bundle import TokenBundle
from vbwd.models.token_bundle_purchase import TokenBundlePurchase
from vbwd.models.addon import AddOn, addon_tarif_plans
from vbwd.models.tarif_plan_category import TarifPlanCategory, tarif_plan_category_plans
from vbwd.models.addon_subscription import AddOnSubscription
from vbwd.models.user_token_balance import UserTokenBalance, TokenTransaction
from vbwd.models.payment_method import PaymentMethod, PaymentMethodTranslation
from vbwd.models.country import Country
from vbwd.models.enums import (
    UserStatus,
    UserRole,
    SubscriptionStatus,
    InvoiceStatus,
    BillingPeriod,
    UserCaseStatus,
    PurchaseStatus,
    LineItemType,
    TokenTransactionType,
)

__all__ = [
    # Models
    "User",
    "UserDetails",
    "UserCase",
    "Currency",
    "TaxClass",
    "Tax",
    "TaxRate",
    "Price",
    "TarifPlan",
    "Subscription",
    "UserInvoice",
    "InvoiceLineItem",
    "PasswordResetToken",
    "Role",
    "Permission",
    "FeatureUsage",
    "TokenBundle",
    "TokenBundlePurchase",
    "AddOn",
    "AddOnSubscription",
    "TarifPlanCategory",
    "UserTokenBalance",
    "TokenTransaction",
    "PaymentMethod",
    "PaymentMethodTranslation",
    "Country",
    "UserAccessLevel",
    # Association tables
    "role_permissions",
    "user_roles",
    "user_access_level_permissions",
    "user_user_access_levels",
    "addon_tarif_plans",
    "tarif_plan_category_plans",
    # Enums
    "UserStatus",
    "UserRole",
    "SubscriptionStatus",
    "InvoiceStatus",
    "BillingPeriod",
    "UserCaseStatus",
    "PurchaseStatus",
    "LineItemType",
    "TokenTransactionType",
]
