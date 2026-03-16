"""EVENT_CONTEXTS — maps event_type → template variable schema + defaults.

Each entry describes:
- description : human-readable label shown in the admin editor
- variables   : dict of var_name → {"type", "description", "example"}

These are the 12 core transactional email events.

At import time, all entries are auto-registered in ``EventContextRegistry``
so other plugins can query the full set via the registry API without needing
to import this module directly. Additional plugins register their own schemas
by calling ``EventContextRegistry.register()`` in ``on_enable()``.
"""
from typing import Dict, Any

EVENT_CONTEXTS: Dict[str, Dict[str, Any]] = {
    "subscription.activated": {
        "description": "Sent when a user's subscription becomes active",
        "variables": {
            "user_name": {
                "type": "string",
                "description": "User display name",
                "example": "Alice",
            },
            "user_email": {
                "type": "string",
                "description": "User email address",
                "example": "alice@example.com",
            },
            "plan_name": {
                "type": "string",
                "description": "Plan display name",
                "example": "Pro Monthly",
            },
            "plan_price": {
                "type": "string",
                "description": "Formatted plan price",
                "example": "$29.00",
            },
            "billing_period": {
                "type": "string",
                "description": "Billing period label",
                "example": "monthly",
            },
            "start_date": {
                "type": "string",
                "description": "Subscription start ISO date",
                "example": "2026-03-14",
            },
            "next_billing_date": {
                "type": "string",
                "description": "Next charge ISO date",
                "example": "2026-04-14",
            },
            "dashboard_url": {
                "type": "string",
                "description": "Link to user dashboard",
                "example": "https://app.example.com/dashboard",
            },
        },
    },
    "subscription.cancelled": {
        "description": "Sent when a subscription is cancelled",
        "variables": {
            "user_name": {
                "type": "string",
                "description": "User display name",
                "example": "Alice",
            },
            "user_email": {
                "type": "string",
                "description": "User email address",
                "example": "alice@example.com",
            },
            "plan_name": {
                "type": "string",
                "description": "Plan display name",
                "example": "Pro Monthly",
            },
            "end_date": {
                "type": "string",
                "description": "Last active date",
                "example": "2026-04-14",
            },
            "resubscribe_url": {
                "type": "string",
                "description": "Link to resubscribe",
                "example": "https://app.example.com/plans",
            },
        },
    },
    "subscription.payment_failed": {
        "description": "Sent immediately when a recurring charge fails",
        "variables": {
            "user_name": {
                "type": "string",
                "description": "User display name",
                "example": "Alice",
            },
            "user_email": {
                "type": "string",
                "description": "User email address",
                "example": "alice@example.com",
            },
            "plan_name": {
                "type": "string",
                "description": "Plan display name",
                "example": "Pro Monthly",
            },
            "amount": {
                "type": "string",
                "description": "Amount that failed to charge",
                "example": "$29.00",
            },
            "retry_date": {
                "type": "string",
                "description": "Next retry ISO date",
                "example": "2026-03-17",
            },
            "update_payment_url": {
                "type": "string",
                "description": "Link to update payment",
                "example": "https://app.example.com/billing",
            },
        },
    },
    "subscription.renewed": {
        "description": "Sent when a subscription is successfully renewed",
        "variables": {
            "user_name": {
                "type": "string",
                "description": "User display name",
                "example": "Alice",
            },
            "user_email": {
                "type": "string",
                "description": "User email address",
                "example": "alice@example.com",
            },
            "plan_name": {
                "type": "string",
                "description": "Plan display name",
                "example": "Pro Monthly",
            },
            "amount_charged": {
                "type": "string",
                "description": "Amount charged",
                "example": "$29.00",
            },
            "next_billing_date": {
                "type": "string",
                "description": "Next charge ISO date",
                "example": "2026-05-14",
            },
            "invoice_url": {
                "type": "string",
                "description": "Link to invoice",
                "example": "https://app.example.com/invoices/abc",
            },
        },
    },
    "trial.started": {
        "description": "Sent when a free trial begins",
        "variables": {
            "user_name": {
                "type": "string",
                "description": "User display name",
                "example": "Alice",
            },
            "user_email": {
                "type": "string",
                "description": "User email address",
                "example": "alice@example.com",
            },
            "plan_name": {
                "type": "string",
                "description": "Plan display name",
                "example": "Pro Trial",
            },
            "trial_end_date": {
                "type": "string",
                "description": "Trial expiry ISO date",
                "example": "2026-03-28",
            },
            "upgrade_url": {
                "type": "string",
                "description": "Link to upgrade page",
                "example": "https://app.example.com/plans",
            },
        },
    },
    "trial.expiring_soon": {
        "description": "Reminder sent 3 days before trial expires",
        "variables": {
            "user_name": {
                "type": "string",
                "description": "User display name",
                "example": "Alice",
            },
            "user_email": {
                "type": "string",
                "description": "User email address",
                "example": "alice@example.com",
            },
            "plan_name": {
                "type": "string",
                "description": "Plan display name",
                "example": "Pro Trial",
            },
            "days_remaining": {
                "type": "integer",
                "description": "Days until trial expires",
                "example": 3,
            },
            "trial_end_date": {
                "type": "string",
                "description": "Trial expiry ISO date",
                "example": "2026-03-17",
            },
            "upgrade_url": {
                "type": "string",
                "description": "Link to upgrade page",
                "example": "https://app.example.com/plans",
            },
        },
    },
    "user.registered": {
        "description": "Welcome email sent on new user registration",
        "variables": {
            "user_name": {
                "type": "string",
                "description": "User display name",
                "example": "Alice",
            },
            "user_email": {
                "type": "string",
                "description": "User email address",
                "example": "alice@example.com",
            },
            "login_url": {
                "type": "string",
                "description": "Link to login page",
                "example": "https://app.example.com/login",
            },
        },
    },
    "user.password_reset": {
        "description": "Sent when a password reset is requested",
        "variables": {
            "user_name": {
                "type": "string",
                "description": "User display name",
                "example": "Alice",
            },
            "user_email": {
                "type": "string",
                "description": "User email address",
                "example": "alice@example.com",
            },
            "reset_url": {
                "type": "string",
                "description": "Password reset link (expires in 1 hour)",
                "example": "https://app.example.com/reset?token=abc",
            },
            "expires_in": {
                "type": "string",
                "description": "Token expiry duration",
                "example": "1 hour",
            },
        },
    },
    "subscription.expired": {
        "description": "Sent when a subscription expires without renewal",
        "variables": {
            "user_name": {
                "type": "string",
                "description": "User display name",
                "example": "Alice",
            },
            "user_email": {
                "type": "string",
                "description": "User email address",
                "example": "alice@example.com",
            },
            "plan_name": {
                "type": "string",
                "description": "Plan display name",
                "example": "Pro Monthly",
            },
            "resubscribe_url": {
                "type": "string",
                "description": "Link to resubscribe / pricing page",
                "example": "https://app.example.com/pricing",
            },
        },
    },
    "invoice.created": {
        "description": "Sent when a new invoice is generated",
        "variables": {
            "user_name": {
                "type": "string",
                "description": "User display name",
                "example": "Alice",
            },
            "user_email": {
                "type": "string",
                "description": "User email address",
                "example": "alice@example.com",
            },
            "invoice_id": {
                "type": "string",
                "description": "Invoice number or ID",
                "example": "INV-2026-0001",
            },
            "amount": {
                "type": "string",
                "description": "Invoice total amount",
                "example": "$29.00",
            },
            "due_date": {
                "type": "string",
                "description": "Payment due ISO date",
                "example": "2026-04-01",
            },
            "invoice_url": {
                "type": "string",
                "description": "Link to invoice detail page",
                "example": "https://app.example.com/invoices/abc",
            },
        },
    },
    "invoice.paid": {
        "description": "Sent when an invoice is successfully paid",
        "variables": {
            "user_name": {
                "type": "string",
                "description": "User display name",
                "example": "Alice",
            },
            "user_email": {
                "type": "string",
                "description": "User email address",
                "example": "alice@example.com",
            },
            "invoice_id": {
                "type": "string",
                "description": "Invoice number or ID",
                "example": "INV-2026-0001",
            },
            "amount": {
                "type": "string",
                "description": "Amount paid",
                "example": "$29.00",
            },
            "paid_date": {
                "type": "string",
                "description": "Payment ISO date",
                "example": "2026-03-16",
            },
            "invoice_url": {
                "type": "string",
                "description": "Link to invoice detail page",
                "example": "https://app.example.com/invoices/abc",
            },
        },
    },
    "contact_form.received": {
        "description": "Sent to the site owner when a contact form is submitted",
        "variables": {
            "widget_slug": {
                "type": "string",
                "description": "Slug of the contact form widget",
                "example": "contact-us",
            },
            "recipient_email": {
                "type": "string",
                "description": "Destination email address (site owner)",
                "example": "admin@example.com",
            },
            "remote_ip": {
                "type": "string",
                "description": "Sender IP address",
                "example": "203.0.113.1",
            },
            "fields": {
                "type": "list",
                "description": "List of form fields [{id, label, value}]",
                "example": '[{"label": "Name", "value": "Bob"}]',
            },
            "fields_text": {
                "type": "string",
                "description": "Plain-text summary of all form fields",
                "example": "  Name: Bob\n  Email: bob@example.com",
            },
        },
    },
}

# Auto-register all core event contexts into the open registry so that
# other plugins and admin routes can use EventContextRegistry.get_all()
# without importing EVENT_CONTEXTS directly.
from plugins.email.src.services.event_context_registry import (
    register as _register,
)  # noqa: E402

for _event_type, _schema in EVENT_CONTEXTS.items():
    _register(_event_type, _schema)
