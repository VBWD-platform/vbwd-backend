"""Dependency injection container."""
from dependency_injector import containers, providers

from vbwd.repositories.user_repository import UserRepository
from vbwd.repositories.user_details_repository import UserDetailsRepository
from vbwd.repositories.invoice_repository import InvoiceRepository
from vbwd.repositories.invoice_line_item_repository import InvoiceLineItemRepository
from vbwd.repositories.currency_repository import CurrencyRepository
from vbwd.repositories.tax_repository import TaxRepository
from vbwd.repositories.password_reset_repository import PasswordResetRepository
from vbwd.repositories.device_token_repository import DeviceTokenRepository
from vbwd.repositories.token_bundle_repository import TokenBundleRepository
from vbwd.repositories.token_bundle_purchase_repository import (
    TokenBundlePurchaseRepository,
)
from vbwd.repositories.token_repository import (
    TokenBalanceRepository,
    TokenTransactionRepository,
)

from vbwd.services.auth_service import AuthService
from vbwd.services.user_service import UserService
from vbwd.services.currency_service import CurrencyService
from vbwd.services.tax_service import TaxService
from vbwd.services.password_reset_service import PasswordResetService
from vbwd.services.device_token_service import DeviceTokenService
from vbwd.services.activity_logger import ActivityLogger
from vbwd.services.token_service import TokenService
from vbwd.services.invoice_service import InvoiceService
from vbwd.services.pdf_service import PdfService, build_default_template_env
from vbwd.services.refund_service import RefundService
from vbwd.services.filesystem import build_uploads_pinned_manager
from vbwd.services.core_settings_store import (
    get_core_settings,
    update_core_settings,
)
from vbwd.services.tags_and_custom_fields import resolve_tags_and_custom_fields
from vbwd.pricing.price_factory import PriceFactory

from vbwd.events.domain import DomainEventDispatcher


class Container(containers.DeclarativeContainer):
    """Application dependency injection container.

    Core only — subscription/addon/plan DI is in the subscription plugin.
    """

    # Configuration
    config = providers.Configuration()

    # Database session - must be overridden with actual db.session
    db_session: providers.Dependency = providers.Dependency()

    # ==================
    # Repositories
    # ==================

    user_repository = providers.Factory(UserRepository, session=db_session)

    user_details_repository = providers.Factory(
        UserDetailsRepository, session=db_session
    )

    invoice_repository = providers.Factory(InvoiceRepository, session=db_session)

    invoice_line_item_repository = providers.Factory(
        InvoiceLineItemRepository, session=db_session
    )

    token_bundle_repository = providers.Factory(
        TokenBundleRepository, session=db_session
    )

    token_bundle_purchase_repository = providers.Factory(
        TokenBundlePurchaseRepository, session=db_session
    )

    token_balance_repository = providers.Factory(
        TokenBalanceRepository, session=db_session
    )

    token_transaction_repository = providers.Factory(
        TokenTransactionRepository, session=db_session
    )

    currency_repository = providers.Factory(CurrencyRepository, session=db_session)

    tax_repository = providers.Factory(TaxRepository, session=db_session)

    device_token_repository = providers.Factory(
        DeviceTokenRepository, session=db_session
    )

    # ==================
    # Services
    # ==================

    auth_service = providers.Factory(AuthService, user_repository=user_repository)

    user_service = providers.Factory(
        UserService,
        user_repository=user_repository,
        user_details_repository=user_details_repository,
    )

    currency_service = providers.Factory(
        CurrencyService,
        currency_repo=currency_repository,
        settings_reader=get_core_settings,
        settings_writer=update_core_settings,
    )

    tax_service = providers.Factory(TaxService, tax_repository=tax_repository)

    # S85.0: the single price-math entry point (D1). Depends only on the core
    # settings reader + CurrencyService — plugin-agnostic (dispatches off the
    # Priceable protocol, never a concrete sellable type).
    price_factory = providers.Factory(
        PriceFactory,
        settings_reader=get_core_settings,
        currency_service=currency_service,
    )

    device_token_service = providers.Factory(
        DeviceTokenService, repository=device_token_repository
    )

    token_service = providers.Factory(
        TokenService,
        balance_repo=token_balance_repository,
        transaction_repo=token_transaction_repository,
        purchase_repo=token_bundle_purchase_repository,
    )

    invoice_service = providers.Factory(
        InvoiceService,
        invoice_repository=invoice_repository,
    )

    refund_service = providers.Factory(
        RefundService,
        invoice_repo=invoice_repository,
        token_service=token_service,
        purchase_repo=token_bundle_purchase_repository,
    )

    # ==================
    # Password Reset
    # ==================

    password_reset_repository = providers.Factory(
        PasswordResetRepository, session=db_session
    )

    activity_logger = providers.Singleton(ActivityLogger)

    # Unified file-access manager (Sprint 58.0) — agnostic core infrastructure.
    # Resolves the var/uploads roots and namespace policies from the
    # environment; consumers resolve it here instead of calling open() on a
    # var path directly. Singleton so the namespace registry is built once.
    # The ``uploads`` namespace is pinned to the uploads root (Sprint 58.3) so
    # blobs keep the legacy ``<UPLOADS_BASE_PATH>/<relative_path>`` layout.
    filesystem_manager = providers.Singleton(build_uploads_pinned_manager)

    # PDF renderer — shared by invoice, booking, and any plugin PDFs.
    # Jinja env points at vbwd/templates/pdf/ for core templates; plugins
    # call pdf_service.register_plugin_template_path(...) during init to
    # contribute their own template dirs.
    pdf_service = providers.Singleton(
        PdfService,
        template_env=providers.Callable(build_default_template_env),
    )

    password_reset_service = providers.Factory(
        PasswordResetService,
        user_repository=user_repository,
        reset_repository=password_reset_repository,
    )

    # S77: generic tags & custom-fields port. Core owns the tables, so the
    # default impl IS the production impl (no no-op fallback); it binds to the
    # live db.session at resolve time. Consumers opt in by registering their
    # entity_type and resolving this port (no plugin import).
    tags_and_custom_fields = providers.Singleton(resolve_tags_and_custom_fields)

    # ==================
    # Event System
    # ==================

    event_dispatcher = providers.Singleton(DomainEventDispatcher)

    # Note: Handlers are registered in app.py after container is wired
