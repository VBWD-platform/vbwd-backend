#!/usr/bin/env python
"""Install demo data: currencies, plans, categories, users, invoices, bundles, add-ons.
Usage: python /app/bin/install_demo_data.py
"""
import sys
sys.path.insert(0, '/app')

from datetime import datetime, timedelta
from decimal import Decimal
import bcrypt
import uuid

from src.extensions import Session
from src.models.user import User
from src.models.user_details import UserDetails
from src.models.currency import Currency
from src.models.price import Price
from src.models.tarif_plan import TarifPlan
from src.models.tarif_plan_category import TarifPlanCategory
from src.models.subscription import Subscription
from src.models.invoice import UserInvoice
from src.models.addon import AddOn
from src.models.addon_subscription import AddOnSubscription
from src.models.token_bundle import TokenBundle
from src.models.enums import (
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
