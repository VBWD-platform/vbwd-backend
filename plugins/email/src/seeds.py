"""Seed default email templates for all 8 event types."""
from __future__ import annotations


DEFAULT_TEMPLATES = [
    {
        "event_type": "subscription.activated",
        "subject": "Welcome to {{ plan_name }}, {{ user_name }}!",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #2c3e50;">Your subscription is active</h1>
  <p>Hi {{ user_name }},</p>
  <p>Your <strong>{{ plan_name }}</strong> subscription is now active.</p>
  <ul>
    <li>Billing: {{ billing_period }}</li>
    <li>Amount: {{ plan_price }}</li>
    <li>Next charge: {{ next_billing_date }}</li>
  </ul>
  <p><a href="{{ dashboard_url }}" style="background:#3498db;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;">Go to Dashboard</a></p>
</body>
</html>""",
        "text_body": "Hi {{ user_name }},\n\nYour {{ plan_name }} subscription is active.\nNext charge: {{ next_billing_date }}\n\nDashboard: {{ dashboard_url }}",
        "is_active": True,
    },
    {
        "event_type": "subscription.cancelled",
        "subject": "Your {{ plan_name }} subscription has been cancelled",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #e74c3c;">Subscription cancelled</h1>
  <p>Hi {{ user_name }},</p>
  <p>Your <strong>{{ plan_name }}</strong> subscription has been cancelled.</p>
  <p>You have access until <strong>{{ end_date }}</strong>.</p>
  <p><a href="{{ resubscribe_url }}" style="background:#3498db;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;">Resubscribe</a></p>
</body>
</html>""",
        "text_body": "Hi {{ user_name }},\n\nYour {{ plan_name }} has been cancelled.\nAccess until: {{ end_date }}\n\nResubscribe: {{ resubscribe_url }}",
        "is_active": True,
    },
    {
        "event_type": "subscription.payment_failed",
        "subject": "Action required: payment failed for {{ plan_name }}",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #e74c3c;">Payment failed</h1>
  <p>Hi {{ user_name }},</p>
  <p>We were unable to charge <strong>{{ amount }}</strong> for your <strong>{{ plan_name }}</strong> subscription.</p>
  <p>We will retry on <strong>{{ retry_date }}</strong>.</p>
  <p><a href="{{ update_payment_url }}" style="background:#e74c3c;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;">Update Payment Method</a></p>
</body>
</html>""",
        "text_body": "Hi {{ user_name }},\n\nPayment of {{ amount }} failed for {{ plan_name }}.\nRetry: {{ retry_date }}\n\nUpdate payment: {{ update_payment_url }}",
        "is_active": True,
    },
    {
        "event_type": "subscription.renewed",
        "subject": "{{ plan_name }} subscription renewed",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #27ae60;">Subscription renewed</h1>
  <p>Hi {{ user_name }},</p>
  <p>Your <strong>{{ plan_name }}</strong> subscription has been renewed.</p>
  <ul>
    <li>Amount charged: {{ amount_charged }}</li>
    <li>Next billing date: {{ next_billing_date }}</li>
  </ul>
  <p><a href="{{ invoice_url }}" style="background:#3498db;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;">View Invoice</a></p>
</body>
</html>""",
        "text_body": "Hi {{ user_name }},\n\n{{ plan_name }} renewed. Charged: {{ amount_charged }}.\nNext: {{ next_billing_date }}\n\nInvoice: {{ invoice_url }}",
        "is_active": True,
    },
    {
        "event_type": "subscription.expired",
        "subject": "Your {{ plan_name }} subscription has expired",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #e74c3c;">Subscription expired</h1>
  <p>Hi {{ user_name }},</p>
  <p>Your <strong>{{ plan_name }}</strong> subscription has expired. You no longer have access to paid features.</p>
  <p><a href="{{ resubscribe_url }}" style="background:#27ae60;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;">Resubscribe</a></p>
</body>
</html>""",
        "text_body": "Hi {{ user_name }},\n\nYour {{ plan_name }} subscription has expired.\n\nResubscribe: {{ resubscribe_url }}",
        "is_active": True,
    },
    {
        "event_type": "invoice.created",
        "subject": "Invoice #{{ invoice_id }} — {{ amount }} due {{ due_date }}",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #2c3e50;">New invoice</h1>
  <p>Hi {{ user_name }},</p>
  <p>Invoice <strong>#{{ invoice_id }}</strong> for <strong>{{ amount }}</strong> is due on {{ due_date }}.</p>
  <p><a href="{{ invoice_url }}" style="background:#3498db;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;">View Invoice</a></p>
</body>
</html>""",
        "text_body": "Hi {{ user_name }},\n\nInvoice #{{ invoice_id }} — {{ amount }} due {{ due_date }}.\n\nView: {{ invoice_url }}",
        "is_active": True,
    },
    {
        "event_type": "invoice.paid",
        "subject": "Payment received — Invoice #{{ invoice_id }}",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #27ae60;">Payment received</h1>
  <p>Hi {{ user_name }},</p>
  <p>We received your payment of <strong>{{ amount }}</strong> for invoice <strong>#{{ invoice_id }}</strong> on {{ paid_date }}.</p>
  <p><a href="{{ invoice_url }}" style="background:#3498db;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;">View Invoice</a></p>
</body>
</html>""",
        "text_body": "Hi {{ user_name }},\n\nPayment of {{ amount }} received for invoice #{{ invoice_id }} on {{ paid_date }}.\n\nView: {{ invoice_url }}",
        "is_active": True,
    },
    {
        "event_type": "trial.started",
        "subject": "Your {{ plan_name }} trial has started",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #2c3e50;">Trial started</h1>
  <p>Hi {{ user_name }},</p>
  <p>Your free trial of <strong>{{ plan_name }}</strong> has started.</p>
  <p>Trial expires: <strong>{{ trial_end_date }}</strong></p>
  <p><a href="{{ upgrade_url }}" style="background:#27ae60;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;">Upgrade Now</a></p>
</body>
</html>""",
        "text_body": "Hi {{ user_name }},\n\nYour {{ plan_name }} trial has started.\nExpires: {{ trial_end_date }}\n\nUpgrade: {{ upgrade_url }}",
        "is_active": True,
    },
    {
        "event_type": "trial.expiring_soon",
        "subject": "Your trial expires in {{ days_remaining }} days",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #f39c12;">Trial expiring soon</h1>
  <p>Hi {{ user_name }},</p>
  <p>Your <strong>{{ plan_name }}</strong> trial expires in <strong>{{ days_remaining }} days</strong> ({{ trial_end_date }}).</p>
  <p><a href="{{ upgrade_url }}" style="background:#f39c12;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;">Upgrade Before It Expires</a></p>
</body>
</html>""",
        "text_body": "Hi {{ user_name }},\n\nYour {{ plan_name }} trial expires in {{ days_remaining }} days ({{ trial_end_date }}).\n\nUpgrade: {{ upgrade_url }}",
        "is_active": True,
    },
    {
        "event_type": "user.registered",
        "subject": "Welcome to VBWD, {{ user_name }}!",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #2c3e50;">Welcome!</h1>
  <p>Hi {{ user_name }},</p>
  <p>Your account has been created. You can log in at any time:</p>
  <p><a href="{{ login_url }}" style="background:#3498db;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;">Log In</a></p>
</body>
</html>""",
        "text_body": "Hi {{ user_name }},\n\nWelcome to VBWD! Log in: {{ login_url }}",
        "is_active": True,
    },
    {
        "event_type": "contact_form.received",
        "subject": "New contact form submission ({{ widget_slug }})",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #2c3e50;">New Contact Form Submission</h1>
  <p><strong>Form:</strong> {{ widget_slug }}</p>
  <table style="width:100%;border-collapse:collapse;margin:16px 0;">
    {% for field in fields %}
    <tr style="border-bottom:1px solid #e2e8f0;">
      <td style="padding:8px;font-weight:600;color:#374151;width:35%;">{{ field.label }}</td>
      <td style="padding:8px;color:#1e293b;">{{ field.value }}</td>
    </tr>
    {% endfor %}
  </table>
  <p style="color:#9ca3af;font-size:12px;">Submitted from IP: {{ remote_ip }}</p>
</body>
</html>""",
        "text_body": "New contact form submission\nForm: {{ widget_slug }}\n\n{{ fields_text }}\n\nIP: {{ remote_ip }}",
        "is_active": True,
    },
    {
        "event_type": "user.password_reset",
        "subject": "Reset your password",
        "html_body": """\
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
  <h1 style="color: #2c3e50;">Password reset</h1>
  <p>Hi {{ user_name }},</p>
  <p>Click the link below to reset your password. This link expires in {{ expires_in }}.</p>
  <p><a href="{{ reset_url }}" style="background:#e74c3c;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;">Reset Password</a></p>
  <p style="color:#999;font-size:12px;">If you did not request this, you can ignore this email.</p>
</body>
</html>""",
        "text_body": "Hi {{ user_name }},\n\nReset your password (expires in {{ expires_in }}): {{ reset_url }}\n\nIgnore if you did not request this.",
        "is_active": True,
    },
]


def seed_default_templates(session) -> int:
    """Insert default templates that do not already exist.

    Returns number of templates created.
    """
    from plugins.email.src.models.email_template import EmailTemplate

    created = 0
    for data in DEFAULT_TEMPLATES:
        exists = (
            session.query(EmailTemplate)
            .filter_by(event_type=data["event_type"])
            .first()
        )
        if exists is None:
            tpl = EmailTemplate(
                event_type=data["event_type"],
                subject=data["subject"],
                html_body=data["html_body"],
                text_body=data["text_body"],
                is_active=data["is_active"],
            )
            session.add(tpl)
            created += 1
    session.commit()
    return created
