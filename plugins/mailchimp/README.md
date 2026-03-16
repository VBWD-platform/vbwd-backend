# Mailchimp (Mandrill) Plugin

Reference implementation of `IEmailSender` using the Mailchimp Transactional API
(formerly Mandrill). When enabled, the email plugin can route all outgoing transactional
emails through Mailchimp instead of direct SMTP.

---

## Prerequisites

- The `email` plugin must be installed and enabled (this plugin provides the sender only)
- A [Mailchimp Transactional](https://mailchimp.com/developer/transactional/) account
  (free tier available, formerly Mandrill)
- Your sending domain must be **verified** in the Mailchimp dashboard

---

## Installation

1. Enable the plugin in `plugins/plugins.json`:
   ```json
   { "name": "mailchimp", "enabled": true }
   ```

2. Add credentials to `plugins/config.json` under the `"mailchimp"` key:
   ```json
   {
     "mailchimp": {
       "mandrill_api_key": "md-xxxxxxxxxxxxxxxxxxxx",
       "from_email": "noreply@yourdomain.com",
       "from_name": "Your App"
     }
   }
   ```

3. Switch the email plugin to use the Mailchimp sender:
   ```json
   {
     "email": {
       "active_sender": "mailchimp"
     }
   }
   ```

No migrations are required — this plugin has no database models.

---

## Configuration

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `mandrill_api_key` | string | `""` | Mandrill API key (starts with `md-`) |
| `from_email` | string | `"noreply@example.com"` | From address (must be a verified sender in Mandrill) |
| `from_name` | string | `"VBWD"` | From display name |

The admin UI exposes these at **Settings → Plugin Config → mailchimp** (Credentials and Sender tabs).

---

## How It Works

On startup, `MandrillEmailSender` is registered with `EmailSenderRegistry` under the key
`"mailchimp"`. When the email plugin's `active_sender` is set to `"mailchimp"`, all calls
to `EmailService.send(message)` are delegated to `MandrillEmailSender.send(message)`.

`MandrillEmailSender` calls the Mandrill `/messages/send` REST endpoint with the rendered
HTML and plain-text bodies produced by the email plugin's Jinja2 templating.

---

## Switching Back to SMTP

Change `active_sender` back to `"smtp"` in the email plugin config:
```json
{
  "email": {
    "active_sender": "smtp"
  }
}
```

No restart required if config hot-reload is enabled (otherwise restart the API container).

---

## Architecture

```
plugins/mailchimp/
├── __init__.py              # MailchimpPlugin class — registers MandrillEmailSender
├── config.json              # Schema + defaults
├── admin-config.json        # Admin UI tab definitions (Credentials, Sender)
└── src/
    └── services/
        └── mandrill_sender.py   # MandrillEmailSender(IEmailSender)
```

`MandrillEmailSender` is a drop-in replacement for `SmtpEmailSender` — both implement
`IEmailSender.send(message: EmailMessage) -> None` and can be selected at runtime via the
`active_sender` config key without code changes.

---

## Related

**Core:** [vbwd-backend](https://github.com/VBWD-platform/vbwd-backend)
