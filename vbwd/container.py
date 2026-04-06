"""Dependency injection container."""
from dependency_injector import containers, providers

from vbwd.repositories.user_repository import UserRepository
from vbwd.repositories.user_details_repository import UserDetailsRepository
from vbwd.repositories.invoice_repository import InvoiceRepository
from vbwd.repositories.invoice_line_item_repository import InvoiceLineItemRepository
from vbwd.repositories.currency_repository import CurrencyRepository
from vbwd.repositories.tax_repository import TaxRepository
from vbwd.repositories.password_reset_repository import PasswordResetRepository
from vbwd.repositories.token_bundle_repository import TokenBundleRepository
from vbwd.repositories.token_bundle_purchase_repository import (
    TokenBundlePurchaseRepository,
)
from vbwd.repositories.token_repository import (
    TokenBalanceRepository,
    TokenTransactionRepository,
)
from vbwd.repositories.subscription_repository import SubscriptionRepository
from vbwd.repositories.tarif_plan_repository import TarifPlanRepository
from vbwd.repositories.tarif_plan_category_repository import (
    TarifPlanCategoryRepository,
)
from vbwd.repositories.addon_repository import AddOnRepository
from vbwd.repositories.addon_subscription_repository import (
    AddOnSubscriptionRepository,
)

from vbwd.services.auth_service import AuthService
from vbwd.services.user_service import UserService
from vbwd.services.currency_service import CurrencyService
from vbwd.services.tax_service import TaxService
from vbwd.services.password_reset_service import PasswordResetService
from vbwd.services.activity_logger import ActivityLogger
from vbwd.services.token_service import TokenService
from vbwd.services.invoice_service import InvoiceService
from vbwd.services.refund_service import RefundService

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

    subscription_repository = providers.Factory(
        SubscriptionRepository, session=db_session
    )

    tarif_plan_repository = providers.Factory(
        TarifPlanRepository, session=db_session
    )

    tarif_plan_category_repository = providers.Factory(
        TarifPlanCategoryRepository, session=db_session
    )

    addon_repository = providers.Factory(AddOnRepository, session=db_session)

    addon_subscription_repository = providers.Factory(
        AddOnSubscriptionRepository, session=db_session
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
        CurrencyService, currency_repository=currency_repository
    )

    tax_service = providers.Factory(TaxService, tax_repository=tax_repository)

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

    password_reset_service = providers.Factory(
        PasswordResetService,
        user_repository=user_repository,
        reset_repository=password_reset_repository,
    )

    # ==================
    # Event System
    # ==================

    event_dispatcher = providers.Singleton(DomainEventDispatcher)

    # Note: Handlers are registered in app.py after container is wired
