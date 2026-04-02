#!/usr/bin/env python
"""Install demo data: currencies, plans, categories, users, invoices, bundles, add-ons,
payment methods.

Usage: python /app/bin/install_demo_data.py
Safe to re-run — all operations are idempotent.
"""
import sys
sys.path.insert(0, '/app')

from datetime import datetime, timedelta
from decimal import Decimal
import bcrypt
import uuid

from vbwd.extensions import Session
from vbwd.models.user import User
from vbwd.models.user_details import UserDetails
from vbwd.models.currency import Currency
from vbwd.models.price import Price
from vbwd.models.tarif_plan import TarifPlan
from vbwd.models.tarif_plan_category import TarifPlanCategory
from vbwd.models.subscription import Subscription
from vbwd.models.invoice import UserInvoice
from vbwd.models.invoice_line_item import InvoiceLineItem
from vbwd.models.addon import AddOn
from vbwd.models.addon_subscription import AddOnSubscription
from vbwd.models.token_bundle import TokenBundle
from vbwd.models.payment_method import PaymentMethod
from vbwd.models.invoice_line_item import InvoiceLineItem, LineItemType
from vbwd.models.country import Country
from vbwd.models.enums import (
    UserStatus, UserRole, BillingPeriod,
    SubscriptionStatus, InvoiceStatus
)

session = Session()

try:
    print("\n=== Creating Currencies ===")

    eur = session.query(Currency).filter_by(code='EUR').first()
    if not eur:
        eur = Currency(code='EUR', name='Euro', symbol='€',
                       exchange_rate=Decimal('1.0'), is_default=True, is_active=True)
        session.add(eur); session.flush()
        print(f'  Created: EUR (id={eur.id})')
    else:
        print(f'  Exists: EUR (id={eur.id})')

    usd = session.query(Currency).filter_by(code='USD').first()
    if not usd:
        usd = Currency(code='USD', name='US Dollar', symbol='$',
                       exchange_rate=Decimal('1.08'), is_default=False, is_active=True)
        session.add(usd); session.flush()
        print(f'  Created: USD (id={usd.id})')
    else:
        print(f'  Exists: USD (id={usd.id})')

    print("\n=== Creating Tarif Plans ===")

    plans_data = [
        {'name': 'Free',       'slug': 'free',       'price': Decimal('0.00'),   'billing_period': BillingPeriod.MONTHLY,  'sort_order': 0, 'features': {'api_calls': 100,       'storage_gb': 1,    'support': 'community', 'default_tokens': 0}},
        {'name': 'Basic',      'slug': 'basic',      'price': Decimal('9.99'),   'billing_period': BillingPeriod.MONTHLY,  'sort_order': 1, 'features': {'api_calls': 1000,      'storage_gb': 10,   'support': 'email',     'default_tokens': 50}},
        {'name': 'Pro',        'slug': 'pro',        'price': Decimal('29.99'),  'billing_period': BillingPeriod.MONTHLY,  'sort_order': 2, 'trial_days': 3, 'features': {'api_calls': 10000, 'storage_gb': 100,  'support': 'priority',  'analytics': True, 'default_tokens': 200}},
        {'name': 'Enterprise', 'slug': 'enterprise', 'price': Decimal('99.99'),  'billing_period': BillingPeriod.MONTHLY,  'sort_order': 3, 'trial_days': 5, 'features': {'api_calls': 'unlimited', 'storage_gb': 1000, 'support': 'dedicated', 'analytics': True, 'sso': True, 'default_tokens': 1000}},
        {'name': 'Lifetime',   'slug': 'lifetime',   'price': Decimal('499.99'), 'billing_period': BillingPeriod.ONE_TIME, 'sort_order': 4, 'features': {'api_calls': 10000,      'storage_gb': 100,  'support': 'priority',  'analytics': True, 'lifetime': True, 'default_tokens': 500}},
    ]

    plans = {}
    for d in plans_data:
        plan = session.query(TarifPlan).filter_by(slug=d['slug']).first()
        if not plan:
            price_obj = Price(price_float=float(d['price']), price_decimal=d['price'],
                              currency_id=eur.id, net_amount=d['price'],
                              gross_amount=d['price'], taxes={})
            session.add(price_obj); session.flush()
            plan = TarifPlan(name=d['name'], slug=d['slug'],
                             description=d.get('description', ''),
                             price_float=float(d['price']), price_id=price_obj.id,
                             price=d['price'], currency='EUR',
                             billing_period=d['billing_period'],
                             trial_days=d.get('trial_days', 0),
                             features=d['features'], is_active=True, sort_order=d['sort_order'])
            session.add(plan); session.flush()
            print(f"  Created: {plan.name} - €{plan.price_float}")
        else:
            if d.get('trial_days', 0):
                plan.trial_days = d['trial_days']; session.flush()
            print(f"  Exists: {plan.name}")
        plans[d['slug']] = plan

    print("\n=== Creating Plan Categories ===")

    categories_data = [
        {'name': 'Root',     'slug': 'root',     'description': 'Core subscription plans.',       'sort_order': 0},
        {'name': 'Backend',  'slug': 'backend',  'description': 'Backend server plugins.',        'sort_order': 1},
        {'name': 'Admin',    'slug': 'fe-admin', 'description': 'Admin frontend plugins.',        'sort_order': 2},
        {'name': 'FE User',  'slug': 'fe-user',  'description': 'User-facing frontend plugins.',  'sort_order': 3},
        {'name': 'Payments', 'slug': 'payments', 'description': 'Payment gateway integrations.',  'sort_order': 4},
    ]

    categories = {}
    for d in categories_data:
        cat = session.query(TarifPlanCategory).filter_by(slug=d['slug']).first()
        if not cat:
            cat = TarifPlanCategory(name=d['name'], slug=d['slug'],
                                    description=d['description'],
                                    sort_order=d['sort_order'], is_single=False)
            session.add(cat); session.flush()
            print(f"  Created: {cat.name}")
        else:
            print(f"  Exists: {cat.name}")
        categories[d['slug']] = cat

    print("\n=== Assigning Core Plans to Root Category ===")

    root_cat = categories.get('root')
    if root_cat:
        for slug in ('free', 'basic', 'pro', 'enterprise'):
            plan = plans.get(slug)
            if plan and plan not in root_cat.tarif_plans:
                root_cat.tarif_plans.append(plan)
                print(f"  Assigned: {plan.name} → root")
            else:
                print(f"  Already assigned or missing: {slug}")
        session.flush()

    print("\n=== Creating Plugin Plans ===")

    plugin_plans_data = [
        {'name': 'Stripe',         'slug': 'plugin-stripe',         'sort_order': 10, 'categories': ['backend', 'fe-admin', 'fe-user', 'payments']},
        {'name': 'Paypal',         'slug': 'plugin-paypal',         'sort_order': 11, 'categories': ['backend', 'fe-admin', 'fe-user', 'payments']},
        {'name': 'Theme-Switcher', 'slug': 'plugin-theme-switcher', 'sort_order': 12, 'categories': ['fe-user']},
        {'name': 'LLM Chat',       'slug': 'plugin-llm-chat',       'sort_order': 13, 'categories': ['fe-user']},
        {'name': 'AI Tarot',       'slug': 'plugin-ai-tarot',       'sort_order': 14, 'categories': ['fe-user', 'backend', 'fe-admin']},
        {'name': 'Import-Export',  'slug': 'plugin-import-export',  'sort_order': 15, 'categories': ['backend']},
        {'name': 'Analytics',      'slug': 'plugin-analytics',      'sort_order': 16, 'categories': ['backend', 'fe-admin']},
    ]

    for d in plugin_plans_data:
        plan = session.query(TarifPlan).filter_by(slug=d['slug']).first()
        if not plan:
            price_obj = Price(price_float=0.0, price_decimal=Decimal('0.00'),
                              currency_id=eur.id, net_amount=Decimal('0.00'),
                              gross_amount=Decimal('0.00'), taxes={})
            session.add(price_obj); session.flush()
            plan = TarifPlan(name=d['name'], slug=d['slug'], description='',
                             price_float=0.0, price_id=price_obj.id,
                             price=Decimal('0.00'), currency='EUR',
                             billing_period=BillingPeriod.YEARLY,
                             trial_days=0, features={}, is_active=True, sort_order=d['sort_order'])
            session.add(plan); session.flush()
            print(f"  Created: {plan.name}")
        else:
            print(f"  Exists: {plan.name}")
        plans[d['slug']] = plan
        for cat_slug in d['categories']:
            cat = categories[cat_slug]
            if plan not in cat.tarif_plans:
                cat.tarif_plans.append(plan)
    session.flush()

    print("\n=== Creating Demo Users ===")

    users_data = [
        {
            'email': 'test@example.com',
            'password': 'TestPass123@',
            'plan_slug': 'free',
            'details': {
                'first_name': 'John',
                'last_name': 'Bach',
                'address_line_1': 'Sunshine Street',
                'city': 'Waldbronn',
                'postal_code': '76337',
                'country': 'DE',
                'phone': '+49123456789',
                'company': 'Sunshine Resort',
            },
        },
        {'email': 'user.free@demo.local', 'password': 'demo123', 'plan_slug': 'free'},
        {'email': 'user.pro@demo.local',  'password': 'demo123', 'plan_slug': 'pro'},
    ]

    users = {}
    for d in users_data:
        user = session.query(User).filter_by(email=d['email']).first()
        if not user:
            h = bcrypt.hashpw(d['password'].encode(), bcrypt.gensalt()).decode()
            user = User(email=d['email'], password_hash=h,
                        status=UserStatus.ACTIVE, role=UserRole.USER)
            session.add(user); session.flush()
            print(f"  Created: {user.email}")
        else:
            print(f"  Exists: {user.email}")
        users[d['email']] = {'user': user, 'plan_slug': d['plan_slug']}

        # Upsert user details if provided
        if d.get('details'):
            det = session.query(UserDetails).filter_by(user_id=user.id).first()
            if not det:
                det = UserDetails(user_id=user.id)
                session.add(det)
            for k, v in d['details'].items():
                setattr(det, k, v)
            session.flush()
            print(f"    Details upserted for {user.email}")

    print("\n=== Creating Subscriptions ===")

    for email, data in users.items():
        user = data['user']
        plan = plans[data['plan_slug']]
        existing = session.query(Subscription).filter_by(
            user_id=user.id, tarif_plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE).first()
        if not existing:
            sub = Subscription(user_id=user.id, tarif_plan_id=plan.id,
                               status=SubscriptionStatus.ACTIVE,
                               started_at=datetime.utcnow() - timedelta(days=15),
                               expires_at=datetime.utcnow() + timedelta(days=15))
            session.add(sub); session.flush()
            users[email]['subscription'] = sub
            print(f"  Created: {email} -> {plan.name}")
        else:
            users[email]['subscription'] = existing
            print(f"  Exists: {email} -> {plan.name}")

    print("\n=== Creating Token Bundles ===")

    for d in [{'name': '100 Tokens', 'token_amount': 100, 'price': Decimal('3.00'), 'sort_order': 0},
              {'name': '500 Tokens', 'token_amount': 500, 'price': Decimal('10.00'), 'sort_order': 1}]:
        bundle = session.query(TokenBundle).filter_by(name=d['name']).first()
        if not bundle:
            bundle = TokenBundle(name=d['name'], description='', token_amount=d['token_amount'],
                                 price=d['price'], is_active=True, sort_order=d['sort_order'])
            session.add(bundle); session.flush()
            print(f"  Created: {bundle.name}")
        else:
            print(f"  Exists: {bundle.name}")

    print("\n=== Creating Add-Ons ===")

    addons_data = [
        {
            'name': 'Extra Storage — 50 GB',
            'slug': 'extra-storage-50gb',
            'description': 'Add 50 GB of storage to your account.',
            'price': Decimal('4.99'),
            'billing_period': BillingPeriod.MONTHLY,
            'sort_order': 0,
            'config': {'storage_gb': 50},
        },
        {
            'name': 'Extra Storage — 200 GB',
            'slug': 'extra-storage-200gb',
            'description': 'Add 200 GB of storage to your account.',
            'price': Decimal('14.99'),
            'billing_period': BillingPeriod.MONTHLY,
            'sort_order': 1,
            'config': {'storage_gb': 200},
        },
        {
            'name': 'Priority Support',
            'slug': 'priority-support',
            'description': 'Get priority email and chat support with a 4-hour response SLA.',
            'price': Decimal('9.99'),
            'billing_period': BillingPeriod.MONTHLY,
            'sort_order': 2,
            'config': {'sla_hours': 4},
        },
        {
            'name': 'Extra API Calls — 10k',
            'slug': 'extra-api-calls-10k',
            'description': 'Add 10,000 additional API calls per month.',
            'price': Decimal('2.99'),
            'billing_period': BillingPeriod.MONTHLY,
            'sort_order': 3,
            'config': {'api_calls': 10000},
        },
        {
            'name': 'White Label',
            'slug': 'white-label',
            'description': 'Remove VBWD branding and use your own logo and domain.',
            'price': Decimal('29.99'),
            'billing_period': BillingPeriod.MONTHLY,
            'sort_order': 4,
            'config': {'remove_branding': True, 'custom_domain': True},
        },
        {
            'name': 'Dedicated Onboarding',
            'slug': 'dedicated-onboarding',
            'description': 'One-time 2-hour onboarding session with a solutions engineer.',
            'price': Decimal('199.00'),
            'billing_period': BillingPeriod.ONE_TIME,
            'sort_order': 5,
            'config': {'sessions': 1, 'duration_hours': 2},
        },
    ]

    for d in addons_data:
        addon = session.query(AddOn).filter_by(slug=d['slug']).first()
        if not addon:
            addon = AddOn(
                name=d['name'],
                slug=d['slug'],
                description=d['description'],
                price=d['price'],
                currency='EUR',
                billing_period=d['billing_period'].value,
                config=d['config'],
                is_active=True,
                sort_order=d['sort_order'],
            )
            session.add(addon)
            session.flush()
            print(f"  Created: {addon.name} - €{addon.price}")
        else:
            print(f"  Exists: {addon.name}")

    print("\n=== Filling Admin Profile ===")

    admin = session.query(User).filter_by(email='admin@example.com').first()
    if admin:
        details = session.query(UserDetails).filter_by(user_id=admin.id).first()
        if not details:
            details = UserDetails(user_id=admin.id)
            session.add(details)
        details.first_name = 'Admin'; details.last_name = 'Superuser'
        details.company = 'VBWD Platform'; details.city = 'Berlin'
        details.country = 'DE'
        session.flush()
        print(f"  Admin profile updated")
    else:
        print("  admin@example.com not found — skipping")

    print("\n=== Creating Payment Methods ===")

    payment_methods_data = [
        {
            'code': 'invoice',
            'name': 'Invoice',
            'description': 'Pay by invoice within 14 days',
            'short_description': 'Pay by invoice',
            'plugin_id': None,
            'is_active': True,
            'is_default': True,
            'position': 0,
            'fee_type': 'none',
            'fee_charged_to': 'customer',
        },
        {
            'code': 'stripe',
            'name': 'stripe',
            'description': '',
            'short_description': 'Pay with Stripe',
            'plugin_id': 'stripe',
            'is_active': True,
            'is_default': False,
            'position': 0,
            'fee_type': 'none',
            'fee_charged_to': 'customer',
        },
        {
            'code': 'paypal',
            'name': 'Paypal',
            'description': '',
            'short_description': 'Pay secure with paypal',
            'plugin_id': 'paypal',
            'is_active': True,
            'is_default': False,
            'position': 0,
            'fee_type': 'none',
            'fee_charged_to': 'customer',
        },
    ]

    for d in payment_methods_data:
        pm = session.query(PaymentMethod).filter_by(code=d['code']).first()
        if not pm:
            pm = PaymentMethod(
                code=d['code'],
                name=d['name'],
                description=d['description'],
                short_description=d['short_description'],
                plugin_id=d['plugin_id'],
                is_active=d['is_active'],
                is_default=d['is_default'],
                position=d['position'],
                fee_type=d['fee_type'],
                fee_charged_to=d['fee_charged_to'],
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

    test_user = session.query(User).filter_by(email='test@example.com').first()
    free_plan = session.query(TarifPlan).filter_by(slug='free').first()
    if test_user and free_plan:
        existing_inv = session.query(UserInvoice).filter_by(
            user_id=test_user.id, tarif_plan_id=free_plan.id
        ).first()
        if not existing_inv:
            test_sub = session.query(Subscription).filter_by(
                user_id=test_user.id, tarif_plan_id=free_plan.id,
                status=SubscriptionStatus.ACTIVE
            ).first()
            inv = UserInvoice(
                user_id=test_user.id,
                tarif_plan_id=free_plan.id,
                subscription_id=test_sub.id if test_sub else None,
                invoice_number=f"INV-DEMO-FREE-001",
                amount=Decimal('0.00'),
                currency='EUR',
                status=InvoiceStatus.PAID,
                payment_method='invoice',
                payment_ref='zero-price',
                invoiced_at=datetime.utcnow() - timedelta(days=30),
                paid_at=datetime.utcnow() - timedelta(days=30),
                subtotal=Decimal('0.00'),
                tax_amount=Decimal('0.00'),
                total_amount=Decimal('0.00'),
            )
            session.add(inv)
            session.flush()
            line = InvoiceLineItem(
                invoice_id=inv.id,
                item_id=free_plan.id,
                description=free_plan.name,
                quantity=1,
                unit_price=Decimal('0.00'),
                total_price=Decimal('0.00'),
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
    print("\n=== Countries ===")
    ENABLED_CODES = {"DE", "FR", "AT", "IT", "PL", "ES", "TH"}
    COUNTRIES = [
        ("AT", "Austria"), ("BE", "Belgium"), ("BG", "Bulgaria"),
        ("HR", "Croatia"), ("CY", "Cyprus"), ("CZ", "Czechia"),
        ("DK", "Denmark"), ("EE", "Estonia"), ("FI", "Finland"),
        ("FR", "France"), ("DE", "Germany"), ("GR", "Greece"),
        ("HU", "Hungary"), ("IE", "Ireland"), ("IT", "Italy"),
        ("LV", "Latvia"), ("LT", "Lithuania"), ("LU", "Luxembourg"),
        ("MT", "Malta"), ("NL", "Netherlands"), ("PL", "Poland"),
        ("PT", "Portugal"), ("RO", "Romania"), ("SK", "Slovakia"),
        ("SI", "Slovenia"), ("ES", "Spain"), ("SE", "Sweden"),
        ("CH", "Switzerland"), ("GB", "United Kingdom"), ("NO", "Norway"),
        ("IS", "Iceland"), ("LI", "Liechtenstein"),
        ("US", "United States"), ("CA", "Canada"), ("MX", "Mexico"),
        ("BR", "Brazil"), ("AR", "Argentina"), ("CL", "Chile"),
        ("CO", "Colombia"),
        ("AU", "Australia"), ("NZ", "New Zealand"),
        ("JP", "Japan"), ("KR", "South Korea"), ("CN", "China"),
        ("TW", "Taiwan"), ("SG", "Singapore"), ("TH", "Thailand"),
        ("IN", "India"), ("ID", "Indonesia"), ("MY", "Malaysia"),
        ("PH", "Philippines"), ("VN", "Vietnam"),
        ("IL", "Israel"), ("AE", "United Arab Emirates"),
        ("SA", "Saudi Arabia"), ("TR", "Turkey"),
        ("ZA", "South Africa"), ("NG", "Nigeria"), ("KE", "Kenya"),
        ("EG", "Egypt"), ("MA", "Morocco"),
        ("UA", "Ukraine"), ("RS", "Serbia"), ("BA", "Bosnia"),
        ("ME", "Montenegro"), ("MK", "North Macedonia"), ("AL", "Albania"),
        ("RU", "Russia"), ("BY", "Belarus"), ("MD", "Moldova"),
        ("GE", "Georgia"),
    ]
    position = 0
    for code, name in COUNTRIES:
        existing = session.query(Country).filter_by(code=code).first()
        if not existing:
            enabled = code in ENABLED_CODES
            country = Country(
                id=uuid.uuid4(),
                code=code,
                name=name,
                is_enabled=enabled,
                position=position if enabled else 999,
            )
            session.add(country)
            if enabled:
                position += 1
    session.commit()
    print(f"  Countries: {session.query(Country).count()} total, "
          f"{session.query(Country).filter_by(is_enabled=True).count()} enabled")

    session.commit()
    print("\n=== Done ===")
    print(f"  Plans:    {session.query(TarifPlan).count()}")
    print(f"  Users:    {session.query(User).count()}")
    print(f"  Bundles:  {session.query(TokenBundle).count()}")
    print(f"  Add-Ons:  {session.query(AddOn).count()}")

except Exception as e:
    session.rollback()
    import traceback; traceback.print_exc()
    sys.exit(1)
finally:
    session.close()
