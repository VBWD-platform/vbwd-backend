# Email Plugin

Transactional email system for vbwd. Provides:
- Jinja2-templated email templates stored in the database per event type
- A pluggable sender backend (SMTP built-in; swap to Mailchimp/Mandrill or any `IEmailSender`)
- Admin API for CRUD, preview with example data, and test sends
- Seed script to populate default templates for all 8 system events

---

## Installation

1. Enable the plugin in `plugins/plugins.json`:
   ```json
   { "name": "email", "enabled": true }
   ```

2. Add configuration to `plugins/config.json` (see [Configuration](#configuration)):
   ```json
   {
     "email": {
       "smtp_host": "localhost",
       "smtp_port": 1025
     }
   }
   ```

3. Run the Alembic migration:
   ```bash
   docker compose exec api python -m alembic upgrade heads
   ```

4. Seed default templates:
   ```bash
   ./plugins/email/bin/populate-db.sh
   ```

---

## Configuration

All settings live in `plugins/config.json` under the `"email"` key.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `smtp_host` | string | `"localhost"` | SMTP server hostname |
| `smtp_port` | number | `587` | Port — `587` STARTTLS, `465` SSL/TLS, `1025` Mailpit dev |
| `smtp_user` | string | `""` | SMTP username (blank = no auth) |
| `smtp_password` | string | `""` | SMTP password |
| `smtp_use_tls` | boolean | `true` | Enable STARTTLS |
| `smtp_from_email` | string | `"noreply@example.com"` | From address |
| `smtp_from_name` | string | `"VBWD"` | From display name |
| `active_sender` | string | `"smtp"` | Which sender backend to use (`smtp`, `mailchimp`, or any registered ID) |
| `log_sends` | boolean | `false` | Log every send to application logger |

The admin UI exposes these under **Settings → Email Templates** (Sender and SMTP tabs).

---

## SMTP Provider Examples

### Mailpit (local dev)
Zero-auth SMTP sandbox that captures all mail at `http://localhost:8025`.
```json
{
  "smtp_host": "mailpit",
  "smtp_port": 1025,
  "smtp_use_tls": false,
  "smtp_user": "",
  "smtp_password": ""
}
```
`mailpit` service is declared in `docker-compose.yaml` and available in the dev network.

### Gmail (app password)
```json
{
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_use_tls": true,
  "smtp_user": "you@gmail.com",
  "smtp_password": "<16-char app password>"
}
```
> Google requires an [App Password](https://support.google.com/accounts/answer/185833) — not your account password.

### SendGrid
```json
{
  "smtp_host": "smtp.sendgrid.net",
  "smtp_port": 587,
  "smtp_use_tls": true,
  "smtp_user": "apikey",
  "smtp_password": "<SENDGRID_API_KEY>"
}
```

### Amazon SES (SMTP interface)
```json
{
  "smtp_host": "email-smtp.us-east-1.amazonaws.com",
  "smtp_port": 587,
  "smtp_use_tls": true,
  "smtp_user": "<SMTP_ACCESS_KEY_ID>",
  "smtp_password": "<SMTP_SECRET_ACCESS_KEY>"
}
```
Generate SMTP credentials in the SES console under **Account → SMTP Settings**.

### Mailgun
```json
{
  "smtp_host": "smtp.mailgun.org",
  "smtp_port": 587,
  "smtp_use_tls": true,
  "smtp_user": "postmaster@mg.yourdomain.com",
  "smtp_password": "<MAILGUN_SMTP_PASSWORD>"
}
```

### Brevo (formerly Sendinblue)
```json
{
  "smtp_host": "smtp-relay.brevo.com",
  "smtp_port": 587,
  "smtp_use_tls": true,
  "smtp_user": "your@email.com",
  "smtp_password": "<BREVO_SMTP_KEY>"
}
```

---

## Alternative Sender Backends

The plugin ships with `SmtpEmailSender` registered under `"smtp"`. Any class that implements
`IEmailSender` can be registered and selected via `active_sender`.

```python
from plugins.email.src.services.email_service import EmailSenderRegistry

class MyCustomSender:
    def send(self, message: EmailMessage) -> None:
        ...  # call your API here

EmailSenderRegistry.register("my-sender", MyCustomSender())
```

Then set `active_sender: "my-sender"` in config.

The built-in `mailchimp` plugin provides `MandrillEmailSender` registered as `"mailchimp"`.
To switch: set `active_sender: "mailchimp"` in the email plugin config and configure the
`mailchimp` plugin with your Mandrill API key.

---

## Event Types

The following event types have seeded default templates:

| Event | Trigger |
|-------|---------|
| `user.registered` | New user sign-up |
| `user.password_reset` | Password reset requested |
| `subscription.activated` | Subscription activated or renewed |
| `subscription.cancelled` | Subscription cancelled by user or admin |
| `subscription.expired` | Subscription reached end date without renewal |
| `invoice.created` | New invoice generated |
| `invoice.paid` | Invoice marked as paid |
| `payment.failed` | Dunning — payment attempt failed |

Templates are editable at **Admin → Settings → Email Templates**.

---

## Admin API

All routes require admin authentication.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/admin/email/templates` | List all templates |
| `POST` | `/api/v1/admin/email/templates` | Create template |
| `GET` | `/api/v1/admin/email/templates/:id` | Get template |
| `PUT` | `/api/v1/admin/email/templates/:id` | Update template |
| `DELETE` | `/api/v1/admin/email/templates/:id` | Delete template |
| `GET` | `/api/v1/admin/email/event-types` | List event types with variable schemas |
| `POST` | `/api/v1/admin/email/templates/preview` | Render template with example data |
| `POST` | `/api/v1/admin/email/test-send` | Send a test email to an address |

---

## Architecture

```
plugins/email/
├── __init__.py              # EmailPlugin class
├── config.json              # Schema + defaults
├── admin-config.json        # Admin UI tab definitions
├── bin/
│   └── populate-db.sh       # Seed script
└── src/
    ├── models/              # EmailTemplate SQLAlchemy model
    ├── repositories/        # EmailTemplateRepository
    ├── services/
    │   ├── email_service.py         # EmailService, EmailSenderRegistry
    │   ├── smtp_sender.py           # SmtpEmailSender (IEmailSender impl)
    │   └── interfaces.py            # IEmailSender, EmailMessage
    ├── handlers.py          # Event handlers (subscribe to system events)
    ├── routes.py            # Admin Blueprint
    ├── seeds.py             # seed_default_templates()
    └── bin/
        └── populate_email.py
```
