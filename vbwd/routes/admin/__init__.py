"""Admin routes package."""
from vbwd.routes.admin.users import admin_users_bp
from vbwd.routes.admin.invoices import admin_invoices_bp
from vbwd.routes.admin.profile import admin_profile_bp
from vbwd.routes.admin.token_bundles import admin_token_bundles_bp
from vbwd.routes.admin.settings import admin_settings_bp
from vbwd.routes.admin.payment_methods import admin_payment_methods_bp
from vbwd.routes.admin.countries import admin_countries_bp
from vbwd.routes.admin.plugins import admin_plugins_bp
from vbwd.routes.admin.tax import admin_tax_bp

__all__ = [
    "admin_users_bp",
    "admin_invoices_bp",
    "admin_profile_bp",
    "admin_token_bundles_bp",
    "admin_settings_bp",
    "admin_payment_methods_bp",
    "admin_countries_bp",
    "admin_plugins_bp",
    "admin_tax_bp",
]
