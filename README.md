# VBWD Backend

Python/Flask REST API for the VBWD SaaS platform — subscription billing, user management, invoicing, token economy, and a plugin system for payment providers and extensions.

## Features

### Subscription Billing
- Tarif plans with billing periods (monthly, yearly, weekly, one-time)
- Plan categories with `is_single` enforcement — one active subscription per user in exclusive categories, unlimited in open categories
- Hierarchical categories (parent/child) with plugin-registerable categories
- Upgrade, downgrade, pause, resume, cancel flows with proration calculation
- Trial periods — automatic trial activation on checkout, conversion to paid on payment
- Zero-price plans activated instantly without payment

### Invoicing
- Auto-generated invoice numbers
- Line items: subscription, token bundle, add-on
- Multi-payment-method support (Stripe, PayPal, YooKassa, bank transfer)
- PDF generation
- Overdue detection and status tracking
- Tax calculation per country

### Token Economy
- Per-user token balance with full transaction ledger
- Token bundles — one-time purchases credited on payment
- Subscription default tokens — credited on activation
- Transaction types: purchase, subscription, usage, adjustment, refund

### Add-ons
- Global and subscription-scoped add-ons
- Pending → active lifecycle tied to invoice payment
- Cancel with expiry-date access continuation

### User Management
- JWT authentication with refresh tokens
- Role-based access (user / admin)
- Profile with billing address, company, VAT
- Password change

### Admin API
- Full CRUD for plans, categories, add-ons, token bundles
- User management (list, detail, edit, create subscription)
- Invoice management with manual payment marking
- Analytics (revenue, subscriptions, users)
- Webhook management
- Payment method configuration per country/currency
- Plugin management (enable, disable, configure)
- Settings (company info, tax, terms)

### Plugin System
- Auto-discovery of `BasePlugin` subclasses in `src/plugins/providers/`
- Dynamic Flask blueprint registration at enable time
- DB-persisted enable/disable state, restored on startup
- Plugins can register plan categories, payment SDK adapters, webhooks
- Built-in plugins: Stripe, PayPal, YooKassa, analytics, Tarot AI, chat

### Event-Driven Architecture
- Domain events: `CheckoutRequestedEvent`, `PaymentCapturedEvent`, `PaymentFailedEvent`, `PaymentRefundedEvent`
- Handlers: `CheckoutHandler` (creates pending items + invoice), `PaymentCapturedHandler` (activates all line items)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | Flask 3.0 |
| Database | PostgreSQL 16 |
| Cache / Queue | Redis 7 |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Auth | JWT (PyJWT) |
| Testing | pytest (300+ tests) |
| Server | Gunicorn |
| Container | Docker + Docker Compose |

---

## Quick Start

### Via monorepo install script (recommended)

```bash
# From the vbwd-sdk-2 root:
./recipes/dev-install-ce.sh

# On a remote server with a domain:
./recipes/dev-install-ce.sh --domain myapp.com --ssl
```

### Standalone

```bash
git clone https://github.com/VBWD-platform/vbwd-backend.git
cd vbwd-backend

cp .env.example .env   # edit secrets, DB credentials, SMTP

make up                # start API + PostgreSQL + Redis
```

The API is available at `http://localhost:5000`.

---

## Docker

```bash
# Start all services (API, PostgreSQL, Redis, Adminer)
make up

# Start with image rebuild
make up-build

# Stop
make down

# Stop and remove volumes (full reset)
make clean

# View logs
make logs

# Shell into the API container
make shell
```

### Run migrations manually

```bash
docker compose exec api alembic upgrade head
```

### Seed demo data

```bash
make reset-demo        # 3 plans, 2 add-ons, 3 token bundles, admin + test user
make seed-test-data    # integration test dataset
```

---

## Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL DSN | `postgresql://vbwd:vbwd@postgres:5432/vbwd` |
| `REDIS_URL` | Redis DSN | `redis://redis:6379/0` |
| `FLASK_SECRET_KEY` | Flask session secret | change in production |
| `JWT_SECRET_KEY` | JWT signing key | change in production |
| `FLASK_ENV` | `development` / `production` | `development` |
| `SMTP_HOST` | SMTP server | — |
| `SMTP_USER` | SMTP username | — |
| `SMTP_PASSWORD` | SMTP password | — |

---

## Testing

```bash
make test              # unit tests (fast, no DB)
make test-unit         # unit tests only
make test-integration  # integration tests (requires make up first)
make test-coverage     # unit tests with coverage report
make pre-commit        # full check: lint + unit + integration
make pre-commit-quick  # quick check: lint + unit
```

Run a specific test file:

```bash
docker compose run --rm test pytest tests/unit/services/test_subscription_service.py -v
```

---

## Project Structure

```
src/
├── events/            # Domain events and dispatcher
├── handlers/          # CheckoutHandler, PaymentCapturedHandler
├── models/            # SQLAlchemy ORM models
│   ├── subscription.py
│   ├── invoice.py
│   ├── tarif_plan.py
│   ├── tarif_plan_category.py
│   ├── addon.py
│   ├── token_bundle.py
│   └── user_token_balance.py
├── plugins/           # Plugin system
│   ├── base.py        # BasePlugin, PluginMetadata
│   ├── manager.py     # PluginManager (discover, enable, disable)
│   └── providers/     # Built-in plugin implementations
├── repositories/      # Data access layer (BaseRepository + typed subclasses)
├── routes/            # Flask blueprints
│   ├── auth.py
│   ├── user.py        # checkout, profile, subscriptions
│   ├── subscriptions.py
│   ├── tarif_plans.py
│   ├── invoices.py
│   └── admin/         # admin-only endpoints
├── services/          # Business logic
├── sdk/               # Payment provider SDK adapters
├── webhooks/          # Incoming webhook processing
└── middleware/        # Auth, CSRF, error handling
alembic/               # Database migrations
tests/
├── unit/
└── integration/
container/
├── python/Dockerfile
└── python/Dockerfile.test
```

---

## API Overview

All routes are prefixed `/api/v1/`.

### Public / User

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Register |
| POST | `/auth/login` | Login → JWT |
| POST | `/auth/refresh` | Refresh token |
| GET | `/tarif-plans` | List plans (optional `?category=<slug>`) |
| GET | `/user/profile` | Get profile |
| PUT | `/user/profile` | Update profile |
| POST | `/user/checkout` | Create invoice + pending items |
| GET | `/user/subscriptions` | Subscription history |
| GET | `/user/subscriptions/active` | Active subscription |
| GET | `/user/subscriptions/active-all` | All active subscriptions |
| POST | `/user/subscriptions/<id>/cancel` | Cancel |
| POST | `/user/subscriptions/<id>/upgrade` | Upgrade plan |
| POST | `/user/subscriptions/<id>/downgrade` | Schedule downgrade |
| GET | `/user/invoices` | Invoice list |
| POST | `/user/invoices/<id>/pay` | Pay invoice |
| GET | `/user/addons` | User add-on subscriptions |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/admin/plans` | List / create plans |
| PUT/DELETE | `/admin/plans/<id>` | Update / delete plan |
| GET/POST | `/admin/tarif-plan-categories` | List / create categories |
| POST | `/admin/tarif-plan-categories/<id>/attach-plans` | Attach plans |
| GET/POST | `/admin/addons` | List / create add-ons |
| GET/POST | `/admin/token-bundles` | List / create token bundles |
| GET | `/admin/users` | User list |
| GET | `/admin/analytics` | Revenue and usage analytics |
| GET/POST | `/admin/plugins` | List / enable / disable plugins |
| GET/PUT | `/admin/settings` | Platform settings |

---

## Plugin Development

```python
# src/plugins/providers/my_plugin.py
from src.plugins.base import BasePlugin, PluginMetadata

class MyPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="my-plugin",
            version="1.0.0",
            description="My custom plugin",
        )

    def on_enable(self):
        pass  # setup, register webhooks, etc.

    def on_disable(self):
        pass

    def get_blueprint(self):
        from src.routes.plugins.my_routes import my_bp
        return my_bp

    def get_url_prefix(self):
        return "/api/v1/plugins/my-plugin"

    def register_categories(self) -> list:
        # Optional: register plan categories on enable
        return [{"name": "My Category", "slug": "my-category", "is_single": False}]
```

Manage plugins via CLI:

```bash
docker compose exec api flask plugins list
docker compose exec api flask plugins enable my-plugin
docker compose exec api flask plugins disable my-plugin
docker compose exec api flask plugins info my-plugin
```

---

## Plugin Directory

| Plugin | Repository | Description |
|--------|-----------|-------------|
| analytics | [vbwd-plugin-analytics](https://github.com/VBWD-platform/vbwd-plugin-analytics) | Request/event analytics for admin dashboard |
| chat | [vbwd-plugin-chat](https://github.com/VBWD-platform/vbwd-plugin-chat) | LLM-powered AI chat with token billing |
| cms | [vbwd-plugin-cms](https://github.com/VBWD-platform/vbwd-plugin-cms) | CMS pages, categories, images, layouts |
| email | [vbwd-plugin-email](https://github.com/VBWD-platform/vbwd-plugin-email) | Email templates, SMTP sender, event-driven delivery |
| ghrm | [vbwd-plugin-ghrm](https://github.com/VBWD-platform/vbwd-plugin-ghrm) | GitHub Release Manager — private package marketplace |
| mailchimp | [vbwd-plugin-mailchimp](https://github.com/VBWD-platform/vbwd-plugin-mailchimp) | Mandrill/Mailchimp email sender backend |
| paypal | [vbwd-plugin-paypal](https://github.com/VBWD-platform/vbwd-plugin-paypal) | PayPal payment SDK adapter and webhooks |
| stripe | [vbwd-plugin-stripe](https://github.com/VBWD-platform/vbwd-plugin-stripe) | Stripe payment SDK adapter and webhooks |
| tarot | [vbwd-plugin-tarot](https://github.com/VBWD-platform/vbwd-plugin-tarot) | Tarot card reading with AI interpretations |
| yookassa | [vbwd-plugin-yookassa](https://github.com/VBWD-platform/vbwd-plugin-yookassa) | YooKassa payment SDK adapter and auto-renewal |

---

## License

BSL 1.1 (Business Source Licence)
