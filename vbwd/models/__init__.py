"""Domain models package."""
from vbwd.models.user import User
from vbwd.models.user_role import RoleDefinition
from vbwd.models.user_details import UserDetails
from vbwd.models.currency import Currency
from vbwd.models.tax import Tax, TaxRate
from vbwd.models.invoice import UserInvoice
from vbwd.models.invoice_line_item import InvoiceLineItem
from vbwd.models.password_reset_token import PasswordResetToken
from vbwd.models.role import (
    AdminRole,
    Role,
    Permission,
    role_permissions,
    user_roles,
)
from vbwd.models.user_access_level import (
    AccessLevel,
    UserAccessLevel,
    user_access_level_permissions,
    user_user_access_levels,
)
from vbwd.models.user_group import UserGroup, user_group_rel
from vbwd.models.feature_usage import FeatureUsage
from vbwd.models.token_bundle import TokenBundle, token_bundle_tax
from vbwd.models.token_bundle_purchase import TokenBundlePurchase
from vbwd.models.user_token_balance import UserTokenBalance, TokenTransaction
from vbwd.models.payment_method import PaymentMethod, PaymentMethodTranslation
from vbwd.models.country import Country
from vbwd.models.plugin_seed_marker import PluginSeedMarker
from vbwd.models.api_key import ApiKey
from vbwd.models.device_token import DeviceToken
from vbwd.models.tag import Tag
from vbwd.models.entity_tag import EntityTag
from vbwd.models.custom_field_def import CustomFieldDef
from vbwd.models.custom_field_value import CustomFieldValue
from vbwd.models.llm_connection import LlmConnection
from vbwd.models.webhook_subscription import WebhookSubscription
from vbwd.models.webhook_delivery import WebhookDelivery
from vbwd.models.enums import (
    UserStatus,
    UserRole,
    SubscriptionStatus,
    InvoiceStatus,
    BillingPeriod,
    PurchaseStatus,
    LineItemType,
    TokenTransactionType,
)

__all__ = [
    # Models
    "User",
    "RoleDefinition",
    "UserDetails",
    "Currency",
    "Tax",
    "TaxRate",
    "UserInvoice",
    "InvoiceLineItem",
    "PasswordResetToken",
    "AdminRole",
    "Role",
    "Permission",
    "FeatureUsage",
    "TokenBundle",
    "token_bundle_tax",
    "TokenBundlePurchase",
    "UserTokenBalance",
    "TokenTransaction",
    "PaymentMethod",
    "PaymentMethodTranslation",
    "Country",
    "PluginSeedMarker",
    "ApiKey",
    "DeviceToken",
    "Tag",
    "EntityTag",
    "CustomFieldDef",
    "CustomFieldValue",
    "LlmConnection",
    "WebhookSubscription",
    "WebhookDelivery",
    "AccessLevel",
    "UserAccessLevel",
    "UserGroup",
    # Association tables
    "role_permissions",
    "user_roles",
    "user_access_level_permissions",
    "user_user_access_levels",
    "user_group_rel",
    # Enums
    "UserStatus",
    "UserRole",
    "SubscriptionStatus",
    "InvoiceStatus",
    "BillingPeriod",
    "PurchaseStatus",
    "LineItemType",
    "TokenTransactionType",
]
