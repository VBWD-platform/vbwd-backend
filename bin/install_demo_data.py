#!/usr/bin/env python
"""Install demo data: currencies, plans, categories, users, invoices, bundles, add-ons,
payment methods.

Usage: python /app/bin/install_demo_data.py
Safe to re-run — all operations are idempotent.
"""
import sys

sys.path.insert(0, "/app")

from datetime import datetime, timedelta
from decimal import Decimal
import bcrypt
import uuid

from vbwd.extensions import Session
from vbwd.models.user import User
from vbwd.models.user_details import UserDetails
from vbwd.models.currency import Currency
from vbwd.services.core_settings_store import update_core_settings
from plugins.subscription.subscription.models.tarif_plan import TarifPlan
from plugins.subscription.subscription.models.tarif_plan_category import (
    TarifPlanCategory,
)
from plugins.subscription.subscription.models.subscription import Subscription
from vbwd.models.invoice import UserInvoice
from vbwd.models.invoice_line_item import InvoiceLineItem
from plugins.subscription.subscription.models.addon import AddOn
from plugins.subscription.subscription.models.addon_subscription import (
    AddOnSubscription,
)
from vbwd.models.token_bundle import TokenBundle
from vbwd.models.payment_method import PaymentMethod
from vbwd.models.invoice_line_item import InvoiceLineItem, LineItemType
from vbwd.models.country import Country
from vbwd.models.role import Role, Permission, user_roles
from vbwd.models.enums import (
    UserStatus,
    UserRole,
    BillingPeriod,
    SubscriptionStatus,
    InvoiceStatus,
)

session = Session()

try:
    print("\n=== Creating Currencies ===")

    eur = session.query(Currency).filter_by(code="EUR").first()
    if not eur:
        eur = Currency(
            code="EUR",
            name="Euro",
            symbol="€",
            exchange_rate=Decimal("1.0"),
        )
        session.add(eur)
        session.flush()
        print(f"  Created: EUR (id={eur.id})")
    else:
        print(f"  Exists: EUR (id={eur.id})")

    usd = session.query(Currency).filter_by(code="USD").first()
    if not usd:
        usd = Currency(
            code="USD",
            name="US Dollar",
            symbol="$",
            exchange_rate=Decimal("1.08"),
        )
        session.add(usd)
        session.flush()
        print(f"  Created: USD (id={usd.id})")
    else:
        print(f"  Exists: USD (id={usd.id})")

    # S84: the active set + default live in the core settings JSON (single
    # source of truth) — not on dropped ``is_active``/``is_default`` columns.
    update_core_settings(
        {"default_currency": "EUR", "active_currencies": ["EUR", "USD"]}
    )
    print("  Settings: default=EUR, active=[EUR, USD]")

    print("\n=== Creating Tarif Plans ===")

    plans_data = [
        {
            "name": "Free",
            "slug": "free",
            "price": Decimal("0.00"),
            "billing_period": BillingPeriod.MONTHLY,
            "sort_order": 0,
            "features": {
                "api_calls": 100,
                "storage_gb": 1,
                "support": "community",
                "default_tokens": 0,
            },
        },
        {
            "name": "Basic",
            "slug": "basic",
            "price": Decimal("9.99"),
            "billing_period": BillingPeriod.MONTHLY,
            "sort_order": 1,
            "features": {
                "api_calls": 1000,
                "storage_gb": 10,
                "support": "email",
                "default_tokens": 50,
            },
        },
        {
            "name": "Pro",
            "slug": "pro",
            "price": Decimal("29.99"),
            "billing_period": BillingPeriod.MONTHLY,
            "sort_order": 2,
            "trial_days": 3,
            "features": {
                "api_calls": 10000,
                "storage_gb": 100,
                "support": "priority",
                "analytics": True,
                "default_tokens": 200,
            },
        },
        {
            "name": "Enterprise",
            "slug": "enterprise",
            "price": Decimal("99.99"),
            "billing_period": BillingPeriod.MONTHLY,
            "sort_order": 3,
            "trial_days": 5,
            "features": {
                "api_calls": "unlimited",
                "storage_gb": 1000,
                "support": "dedicated",
                "analytics": True,
                "sso": True,
                "default_tokens": 1000,
            },
        },
        {
            "name": "Lifetime",
            "slug": "lifetime",
            "price": Decimal("499.99"),
            "billing_period": BillingPeriod.ONE_TIME,
            "sort_order": 4,
            "features": {
                "api_calls": 10000,
                "storage_gb": 100,
                "support": "priority",
                "analytics": True,
                "lifetime": True,
                "default_tokens": 500,
            },
        },
    ]

    plans = {}
    for d in plans_data:
        plan = session.query(TarifPlan).filter_by(slug=d["slug"]).first()
        if not plan:
            plan = TarifPlan(
                name=d["name"],
                slug=d["slug"],
                description=d.get("description", ""),
                price=float(d["price"]),
                billing_period=d["billing_period"],
                trial_days=d.get("trial_days", 0),
                features=d["features"],
                is_active=True,
                sort_order=d["sort_order"],
            )
            session.add(plan)
            session.flush()
            print(f"  Created: {plan.name} - €{plan.price}")
        else:
            if d.get("trial_days", 0):
                plan.trial_days = d["trial_days"]
                session.flush()
            print(f"  Exists: {plan.name}")
        plans[d["slug"]] = plan

    print("\n=== Creating Plan Categories ===")

    categories_data = [
        {
            "name": "Root",
            "slug": "root",
            "description": "Core subscription plans.",
            "sort_order": 0,
        },
        {
            "name": "Backend",
            "slug": "backend",
            "description": "Backend server plugins.",
            "sort_order": 1,
        },
        {
            "name": "Admin",
            "slug": "fe-admin",
            "description": "Admin frontend plugins.",
            "sort_order": 2,
        },
        {
            "name": "FE User",
            "slug": "fe-user",
            "description": "User-facing frontend plugins.",
            "sort_order": 3,
        },
        {
            "name": "Payments",
            "slug": "payments",
            "description": "Payment gateway integrations.",
            "sort_order": 4,
        },
    ]

    categories = {}
    for d in categories_data:
        cat = session.query(TarifPlanCategory).filter_by(slug=d["slug"]).first()
        if not cat:
            cat = TarifPlanCategory(
                name=d["name"],
                slug=d["slug"],
                description=d["description"],
                sort_order=d["sort_order"],
                is_single=False,
            )
            session.add(cat)
            session.flush()
            print(f"  Created: {cat.name}")
        else:
            print(f"  Exists: {cat.name}")
        categories[d["slug"]] = cat

    print("\n=== Assigning Core Plans to Root Category ===")

    root_cat = categories.get("root")
    if root_cat:
        for slug in ("free", "basic", "pro", "enterprise"):
            plan = plans.get(slug)
            if plan and plan not in root_cat.tarif_plans:
                root_cat.tarif_plans.append(plan)
                print(f"  Assigned: {plan.name} → root")
            else:
                print(f"  Already assigned or missing: {slug}")
        session.flush()

    print("\n=== Creating Plugin Plans ===")

    plugin_plans_data = [
        {
            "name": "Stripe",
            "slug": "plugin-stripe",
            "sort_order": 10,
            "categories": ["backend", "fe-admin", "fe-user", "payments"],
        },
        {
            "name": "Paypal",
            "slug": "plugin-paypal",
            "sort_order": 11,
            "categories": ["backend", "fe-admin", "fe-user", "payments"],
        },
        {
            "name": "Theme-Switcher",
            "slug": "plugin-theme-switcher",
            "sort_order": 12,
            "categories": ["fe-user"],
        },
        {
            "name": "LLM Chat",
            "slug": "plugin-llm-chat",
            "sort_order": 13,
            "categories": ["fe-user"],
        },
        {
            "name": "AI Tarot",
            "slug": "plugin-ai-tarot",
            "sort_order": 14,
            "categories": ["fe-user", "backend", "fe-admin"],
        },
        {
            "name": "Import-Export",
            "slug": "plugin-import-export",
            "sort_order": 15,
            "categories": ["backend"],
        },
        {
            "name": "Analytics",
            "slug": "plugin-analytics",
            "sort_order": 16,
            "categories": ["backend", "fe-admin"],
        },
    ]

    for d in plugin_plans_data:
        plan = session.query(TarifPlan).filter_by(slug=d["slug"]).first()
        if not plan:
            plan = TarifPlan(
                name=d["name"],
                slug=d["slug"],
                description="",
                price=0.0,
                billing_period=BillingPeriod.YEARLY,
                trial_days=0,
                features={},
                is_active=True,
                sort_order=d["sort_order"],
            )
            session.add(plan)
            session.flush()
            print(f"  Created: {plan.name}")
        else:
            print(f"  Exists: {plan.name}")
        plans[d["slug"]] = plan
        for cat_slug in d["categories"]:
            cat = categories[cat_slug]
            if plan not in cat.tarif_plans:
                cat.tarif_plans.append(plan)
    session.flush()

    print("\n=== Creating Demo Users ===")

    users_data = [
        {
            "email": "admin@example.com",
            "password": "AdminPass123@",
            "plan_slug": "free",
            "role": "SUPER_ADMIN",
            "details": {
                "first_name": "Admin",
                "last_name": "User",
            },
        },
        {
            "email": "test@example.com",
            "password": "TestPass123@",
            "plan_slug": "free",
            "details": {
                "first_name": "John",
                "last_name": "Bach",
                "address_line_1": "Sunshine Street",
                "city": "Waldbronn",
                "postal_code": "76337",
                "country": "DE",
                "phone": "+49123456789",
                "company": "Sunshine Resort",
            },
        },
        {"email": "user.free@demo.local", "password": "demo123", "plan_slug": "free"},
        {
            "email": "user.pro@demo.local",
            "password": "demo123",
            "plan_slug": "pro",
            "role": "ADMIN",
        },
    ]

    users = {}
    for d in users_data:
        user = session.query(User).filter_by(email=d["email"]).first()
        if not user:
            h = bcrypt.hashpw(d["password"].encode(), bcrypt.gensalt()).decode()
            user_role = UserRole(d.get("role", "USER"))
            user = User(
                email=d["email"],
                password_hash=h,
                status=UserStatus.ACTIVE,
                role=user_role,
            )
            session.add(user)
            session.flush()
            print(f"  Created: {user.email}")
        else:
            print(f"  Exists: {user.email}")
        users[d["email"]] = {"user": user, "plan_slug": d["plan_slug"]}

        # Upsert user details if provided
        if d.get("details"):
            det = session.query(UserDetails).filter_by(user_id=user.id).first()
            if not det:
                det = UserDetails(user_id=user.id)
                session.add(det)
            for k, v in d["details"].items():
                setattr(det, k, v)
            session.flush()
            print(f"    Details upserted for {user.email}")

    print("\n=== Creating Subscriptions ===")

    for email, data in users.items():
        user = data["user"]
        plan = plans[data["plan_slug"]]
        existing = (
            session.query(Subscription)
            .filter_by(
                user_id=user.id, tarif_plan_id=plan.id, status=SubscriptionStatus.ACTIVE
            )
            .first()
        )
        if not existing:
            sub = Subscription(
                user_id=user.id,
                tarif_plan_id=plan.id,
                status=SubscriptionStatus.ACTIVE,
                started_at=datetime.utcnow() - timedelta(days=15),
                expires_at=datetime.utcnow() + timedelta(days=15),
            )
            session.add(sub)
            session.flush()
            users[email]["subscription"] = sub
            print(f"  Created: {email} -> {plan.name}")
        else:
            users[email]["subscription"] = existing
            print(f"  Exists: {email} -> {plan.name}")

    print("\n=== Creating Token Bundles ===")

    for d in [
        {
            "name": "100 Tokens",
            "token_amount": 100,
            "price": Decimal("3.00"),
            "sort_order": 0,
        },
        {
            "name": "500 Tokens",
            "token_amount": 500,
            "price": Decimal("10.00"),
            "sort_order": 1,
        },
    ]:
        bundle = session.query(TokenBundle).filter_by(name=d["name"]).first()
        if not bundle:
            bundle = TokenBundle(
                name=d["name"],
                description="",
                token_amount=d["token_amount"],
                price=d["price"],
                is_active=True,
                sort_order=d["sort_order"],
            )
            session.add(bundle)
            session.flush()
            print(f"  Created: {bundle.name}")
        else:
            print(f"  Exists: {bundle.name}")

    print("\n=== Creating Add-Ons ===")

    addons_data = [
        {
            "name": "Extra Storage — 50 GB",
            "slug": "extra-storage-50gb",
            "description": "Add 50 GB of storage to your account.",
            "price": Decimal("4.99"),
            "billing_period": BillingPeriod.MONTHLY,
            "sort_order": 0,
            "config": {"storage_gb": 50},
        },
        {
            "name": "Extra Storage — 200 GB",
            "slug": "extra-storage-200gb",
            "description": "Add 200 GB of storage to your account.",
            "price": Decimal("14.99"),
            "billing_period": BillingPeriod.MONTHLY,
            "sort_order": 1,
            "config": {"storage_gb": 200},
        },
        {
            "name": "Priority Support",
            "slug": "priority-support",
            "description": "Get priority email and chat support with a 4-hour response SLA.",
            "price": Decimal("9.99"),
            "billing_period": BillingPeriod.MONTHLY,
            "sort_order": 2,
            "config": {"sla_hours": 4},
        },
        {
            "name": "Extra API Calls — 10k",
            "slug": "extra-api-calls-10k",
            "description": "Add 10,000 additional API calls per month.",
            "price": Decimal("2.99"),
            "billing_period": BillingPeriod.MONTHLY,
            "sort_order": 3,
            "config": {"api_calls": 10000},
        },
        {
            "name": "White Label",
            "slug": "white-label",
            "description": "Remove VBWD branding and use your own logo and domain.",
            "price": Decimal("29.99"),
            "billing_period": BillingPeriod.MONTHLY,
            "sort_order": 4,
            "config": {"remove_branding": True, "custom_domain": True},
        },
        {
            "name": "Dedicated Onboarding",
            "slug": "dedicated-onboarding",
            "description": "One-time 2-hour onboarding session with a solutions engineer.",
            "price": Decimal("199.00"),
            "billing_period": BillingPeriod.ONE_TIME,
            "sort_order": 5,
            "config": {"sessions": 1, "duration_hours": 2},
        },
    ]

    for d in addons_data:
        addon = session.query(AddOn).filter_by(slug=d["slug"]).first()
        if not addon:
            addon = AddOn(
                name=d["name"],
                slug=d["slug"],
                description=d["description"],
                price=d["price"],
                billing_period=d["billing_period"].value,
                config=d["config"],
                is_active=True,
                sort_order=d["sort_order"],
            )
            session.add(addon)
            session.flush()
            print(f"  Created: {addon.name} - €{addon.price}")
        else:
            print(f"  Exists: {addon.name}")

    print("\n=== Filling Admin Profile ===")

    admin = session.query(User).filter_by(email="admin@example.com").first()
    if admin:
        details = session.query(UserDetails).filter_by(user_id=admin.id).first()
        if not details:
            details = UserDetails(user_id=admin.id)
            session.add(details)
        details.first_name = "Admin"
        details.last_name = "Superuser"
        details.company = "VBWD Platform"
        details.city = "Berlin"
        details.country = "DE"
        session.flush()
        print(f"  Admin profile updated")
    else:
        print("  admin@example.com not found — skipping")

    print("\n=== Creating Payment Methods ===")

    payment_methods_data = [
        {
            "code": "invoice",
            "name": "Invoice",
            "description": "Pay by invoice within 14 days",
            "short_description": "Pay by invoice",
            "plugin_id": None,
            "is_active": True,
            "is_default": True,
            "position": 0,
            "fee_type": "none",
            "fee_charged_to": "customer",
        },
        {
            "code": "stripe",
            "name": "stripe",
            "description": "",
            "short_description": "Pay with Stripe",
            "plugin_id": "stripe",
            "is_active": True,
            "is_default": False,
            "position": 0,
            "fee_type": "none",
            "fee_charged_to": "customer",
        },
        {
            "code": "paypal",
            "name": "Paypal",
            "description": "",
            "short_description": "Pay secure with paypal",
            "plugin_id": "paypal",
            "is_active": True,
            "is_default": False,
            "position": 0,
            "fee_type": "none",
            "fee_charged_to": "customer",
        },
    ]

    for d in payment_methods_data:
        pm = session.query(PaymentMethod).filter_by(code=d["code"]).first()
        if not pm:
            pm = PaymentMethod(
                code=d["code"],
                name=d["name"],
                description=d["description"],
                short_description=d["short_description"],
                plugin_id=d["plugin_id"],
                is_active=d["is_active"],
                is_default=d["is_default"],
                position=d["position"],
                fee_type=d["fee_type"],
                fee_charged_to=d["fee_charged_to"],
                currencies=[],
                countries=[],
                config={},
            )
            session.add(pm)
            session.flush()
            print(f"  Created: {pm.code}")
        else:
            print(f"  Exists: {pm.code}")

    print("\n=== Creating Sample Invoice for test@example.com ===")

    test_user = session.query(User).filter_by(email="test@example.com").first()
    free_plan = session.query(TarifPlan).filter_by(slug="free").first()
    if test_user and free_plan:
        existing_inv = (
            session.query(UserInvoice)
            .filter_by(invoice_number="INV-DEMO-FREE-001")
            .first()
        )
        if not existing_inv:
            test_sub = (
                session.query(Subscription)
                .filter_by(
                    user_id=test_user.id,
                    tarif_plan_id=free_plan.id,
                    status=SubscriptionStatus.ACTIVE,
                )
                .first()
            )
            # Core UserInvoice has no plan/subscription FK after the subscription
            # extraction — the subscription link lives on the SUBSCRIPTION line
            # item below (item_id == subscription.id).
            inv = UserInvoice(
                user_id=test_user.id,
                invoice_number="INV-DEMO-FREE-001",
                amount=Decimal("0.00"),
                currency="EUR",
                status=InvoiceStatus.PAID,
                payment_method="invoice",
                payment_ref="zero-price",
                invoiced_at=datetime.utcnow() - timedelta(days=30),
                paid_at=datetime.utcnow() - timedelta(days=30),
                subtotal=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                total_amount=Decimal("0.00"),
            )
            session.add(inv)
            session.flush()
            line = InvoiceLineItem(
                invoice_id=inv.id,
                item_id=test_sub.id if test_sub else free_plan.id,
                description=free_plan.name,
                quantity=1,
                unit_price=Decimal("0.00"),
                total_price=Decimal("0.00"),
                item_type=LineItemType.SUBSCRIPTION,
            )
            session.add(line)
            session.flush()
            print(f"  Created: INV-DEMO-FREE-001 for test@example.com")
        else:
            print(f"  Exists: invoice for test@example.com / free plan")
    else:
        print("  test@example.com or free plan not found — skipping invoice")

    # ── Countries ─────────────────────────────────────────────────
    # Foundational reference data — delegate to the shared core seeder
    # (single source of truth; ungated + idempotent). DACH (DE/AT/CH) is
    # enabled by default there.
    print("\n=== Countries ===")
    from vbwd.services.country_seeder import seed_countries

    seed_countries(session)
    print(
        f"  Countries: {session.query(Country).count()} total, "
        f"{session.query(Country).filter_by(is_enabled=True).count()} enabled"
    )

    # ── Roles, Permissions & User Access Levels ────────────────
    # Foundational RBAC data (permission catalog, admin roles, user access
    # levels) is owned by the shared, idempotent core seeder — the single
    # source of truth that runs on EVERY install, not only with demo data.
    # Run it here so this script standalone still produces a complete DB.
    print("\n=== Roles, Permissions & Access Levels (core seeder) ===")
    from vbwd.services.rbac_seeder import seed_default_rbac

    seed_result = seed_default_rbac(session)
    print(
        f"  roles created: {seed_result.roles_created}, "
        f"permissions created: {seed_result.permissions_created}, "
        f"user access levels created: {seed_result.user_access_levels_created}"
    )

    # ── Observer demo role ─────────────────────────────────────
    # A demo fixture (NOT a core role): a view-only admin role the fe-admin
    # ``observer-login`` e2e test depends on (user.pro@demo.local sees a
    # limited sidebar + gets 403 on /admin/settings/access). Its view
    # permissions come from the core catalog seeded above — resolve them
    # leniently and skip any that are absent.
    print("\n=== Observer demo role ===")
    observer_role = session.query(Role).filter_by(slug="observer").first()
    if observer_role is None:
        observer_role = Role(
            id=uuid.uuid4(),
            name="Observer",
            slug="observer",
            description="View-only access level",
            is_system=True,
        )
        session.add(observer_role)
        session.flush()
        print("  Created role: observer")
    if not observer_role.permissions:
        view_perms = ["analytics.view", "users.view", "invoices.view", "settings.view"]
        for perm_name in view_perms:
            perm = session.query(Permission).filter_by(name=perm_name).first()
            if perm:
                observer_role.permissions.append(perm)

    # Assign observer to user.pro@demo.local
    pro_user = session.query(User).filter_by(email="user.pro@demo.local").first()
    if pro_user and observer_role:
        if (
            not session.query(user_roles)
            .filter_by(user_id=pro_user.id, role_id=observer_role.id)
            .first()
        ):
            session.execute(
                user_roles.insert().values(
                    user_id=pro_user.id, role_id=observer_role.id
                )
            )
            print(f"  Assigned observer to: {pro_user.email}")

    session.commit()
    print(f"  Admin roles: {session.query(Role).count()}")

    # ── Assign User Access Levels to demo users ────────────────
    # The levels themselves are seeded by the core seeder above; here we only
    # ASSIGN them to demo users, looking each up by slug and skipping if absent.
    print("\n=== Assigning User Access Levels to demo users ===")

    from vbwd.models.user_access_level import (
        UserAccessLevel,
        user_user_access_levels,
    )

    for email, level_slug in [
        ("user.free@demo.local", "logged-in"),
        ("user.pro@demo.local", "subscribed-pro"),
        ("test@example.com", "logged-in"),
    ]:
        user = session.query(User).filter_by(email=email).first()
        level = session.query(UserAccessLevel).filter_by(slug=level_slug).first()
        if user and level:
            if (
                not session.query(user_user_access_levels)
                .filter_by(
                    user_id=user.id,
                    user_access_level_id=level.id,
                )
                .first()
            ):
                session.execute(
                    user_user_access_levels.insert().values(
                        user_id=user.id,
                        user_access_level_id=level.id,
                    )
                )
                print(f"  Assigned {level_slug} to {email}")

    session.commit()
    print(f"  User access levels: " f"{session.query(UserAccessLevel).count()}")
    print("\n=== Done ===")
    print(f"  Plans:    {session.query(TarifPlan).count()}")
    print(f"  Users:    {session.query(User).count()}")
    print(f"  Bundles:  {session.query(TokenBundle).count()}")
    print(f"  Add-Ons:  {session.query(AddOn).count()}")

except Exception as e:
    session.rollback()
    import traceback

    traceback.print_exc()
    sys.exit(1)
finally:
    session.close()
