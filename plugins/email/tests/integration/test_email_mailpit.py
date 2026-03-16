"""Mailpit integration tests for the email plugin.

Each test:
  1. Seeds the default email template for the event under test.
  2. Emits the event via EventBus (the same code path used in production).
  3. Polls the Mailpit HTTP API to verify the email was delivered with the
     correct subject, recipient, and body content.

Prerequisites:
  - Mailpit running at smtp://mailpit:1025 (SMTP) and http://mailpit:8025 (API).
  - Both addresses are available inside the Docker test network.

Run:
    docker compose run --rm test python -m pytest \
        plugins/email/tests/integration/test_email_mailpit.py -v

Skipped automatically when the MAILPIT_API_URL environment variable is not set
and the default Mailpit host is unreachable.
"""
from __future__ import annotations

import os
import time
import pytest
import requests

from src.events.bus import EventBus
from plugins.email.src.handlers import register_handlers
from plugins.email.src.models.email_template import EmailTemplate

# ── Mailpit helpers ────────────────────────────────────────────────────────────

MAILPIT_API = os.getenv("MAILPIT_API_URL", "http://mailpit:8025")
SMTP_HOST = os.getenv("MAILPIT_SMTP_HOST", "mailpit")
SMTP_PORT = int(os.getenv("MAILPIT_SMTP_PORT", "1025"))

_SMTP_CFG = {
    "smtp_host": SMTP_HOST,
    "smtp_port": SMTP_PORT,
    "smtp_use_tls": False,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from_email": "noreply@vbwd.test",
    "smtp_from_name": "VBWD Test",
}


def _mailpit_reachable() -> bool:
    try:
        r = requests.get(f"{MAILPIT_API}/api/v1/messages", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _clear_mailpit() -> None:
    """Delete all messages from Mailpit inbox."""
    requests.delete(f"{MAILPIT_API}/api/v1/messages", timeout=5)


def _wait_for_message(to: str, timeout: float = 5.0, poll: float = 0.3) -> dict | None:
    """Poll Mailpit until a message arrives for *to*, return it or None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = requests.get(f"{MAILPIT_API}/api/v1/messages", timeout=3)
        messages = resp.json().get("messages") or []
        for msg in messages:
            recipients = [r.get("Address", "") for r in (msg.get("To") or [])]
            if to in recipients:
                # Fetch full message body
                msg_id = msg["ID"]
                full = requests.get(
                    f"{MAILPIT_API}/api/v1/message/{msg_id}", timeout=3
                ).json()
                return full
        time.sleep(poll)
    return None


# ── Fixtures ───────────────────────────────────────────────────────────────────

requires_mailpit = pytest.mark.skipif(
    not _mailpit_reachable(),
    reason="Mailpit not reachable — set MAILPIT_API_URL or start docker compose",
)


@pytest.fixture(scope="module")
def app():
    from src.app import create_app

    url = _test_db_url()
    _ensure_test_db(url)
    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "RATELIMIT_ENABLED": False,
        "SECRET_KEY": "test-secret",
        "JWT_SECRET_KEY": "test-jwt-secret",
        "FLASK_SECRET_KEY": "test-secret",
    }
    return create_app(test_config)


@pytest.fixture(scope="module")
def db(app):
    from src.extensions import db as _db

    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(autouse=True)
def clear_inbox():
    _clear_mailpit()
    yield
    _clear_mailpit()


def _test_db_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, dbname = base.rpartition("/")
    dbname = dbname.split("?")[0]
    return f"{prefix}/{dbname}_mailpit_test"


def _ensure_test_db(url: str) -> None:
    from sqlalchemy import create_engine, text

    main_url = url.rsplit("/", 1)[0] + "/postgres"
    dbname = url.rsplit("/", 1)[1].split("?")[0]
    engine = create_engine(main_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        engine.dispose()


def _seed(
    app, db, event_type: str, subject_tpl: str, html_tpl: str, text_tpl: str = ""
) -> None:
    with app.app_context():
        existing = (
            db.session.query(EmailTemplate).filter_by(event_type=event_type).first()
        )
        if existing:
            existing.subject = subject_tpl
            existing.html_body = html_tpl
            existing.text_body = text_tpl
            existing.is_active = True
        else:
            db.session.add(
                EmailTemplate(
                    event_type=event_type,
                    subject=subject_tpl,
                    html_body=html_tpl,
                    text_body=text_tpl,
                    is_active=True,
                )
            )
        db.session.commit()


def _bus(app) -> EventBus:
    bus = EventBus()
    with app.app_context():
        register_handlers(bus, _SMTP_CFG)
    return bus


# ── SMTP connectivity test ─────────────────────────────────────────────────────


@requires_mailpit
class TestSmtpConnectivity:
    def test_smtp_connection_succeeds(self):
        """Direct SMTP connection to Mailpit succeeds without error."""
        import smtplib

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as smtp:
            code, _ = smtp.noop()
        assert code == 250

    def test_smtp_sends_and_mailpit_receives(self):
        """A raw SMTP send is captured by Mailpit."""
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText("Hello from test", "plain")
        msg["Subject"] = "SMTP connectivity check"
        msg["From"] = "sender@vbwd.test"
        msg["To"] = "recv@vbwd.test"
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as smtp:
            smtp.send_message(msg)
        received = _wait_for_message("recv@vbwd.test")
        assert received is not None, "Mailpit did not receive the test message"
        assert "SMTP connectivity check" in received.get("Subject", "")


# ── Per-event tests ────────────────────────────────────────────────────────────


@requires_mailpit
class TestUserRegisteredEmail:
    def test_email_delivered_to_correct_address(self, app, db):
        _seed(
            app,
            db,
            "user.registered",
            "Welcome {{ user_name }}!",
            "<h1>Hi {{ user_name }}</h1><p>Email: {{ user_email }}</p>",
            "Hi {{ user_name }}, email: {{ user_email }}",
        )
        bus = _bus(app)
        bus.publish(
            "user.registered",
            {
                "user_email": "alice@vbwd.test",
                "user_name": "Alice",
                "login_url": "http://localhost/login",
            },
        )
        msg = _wait_for_message("alice@vbwd.test")
        assert msg is not None, "No email received for user.registered"

    def test_subject_rendered_with_name(self, app, db):
        _seed(app, db, "user.registered", "Welcome {{ user_name }}!", "<p>Hi</p>")
        bus = _bus(app)
        bus.publish(
            "user.registered", {"user_email": "bob@vbwd.test", "user_name": "Bob"}
        )
        msg = _wait_for_message("bob@vbwd.test")
        assert msg is not None
        assert "Bob" in msg.get("Subject", ""), f"Subject was: {msg.get('Subject')}"

    def test_html_body_contains_user_name(self, app, db):
        _seed(
            app,
            db,
            "user.registered",
            "Welcome",
            "<p>Hello {{ user_name }}, welcome!</p>",
        )
        bus = _bus(app)
        bus.publish(
            "user.registered", {"user_email": "carol@vbwd.test", "user_name": "Carol"}
        )
        msg = _wait_for_message("carol@vbwd.test")
        assert msg is not None
        html = msg.get("HTML", "")
        assert "Carol" in html, f"Name not in HTML body: {html[:200]}"


@requires_mailpit
class TestUserPasswordResetEmail:
    def test_reset_email_delivered(self, app, db):
        _seed(
            app,
            db,
            "user.password_reset",
            "Reset your password",
            "<a href='{{ reset_url }}'>Reset</a>",
        )
        bus = _bus(app)
        bus.publish(
            "user.password_reset",
            {
                "user_email": "dave@vbwd.test",
                "user_name": "Dave",
                "reset_url": "http://localhost/reset/token123",
                "expires_in": "1 hour",
            },
        )
        msg = _wait_for_message("dave@vbwd.test")
        assert msg is not None

    def test_reset_url_in_body(self, app, db):
        _seed(
            app,
            db,
            "user.password_reset",
            "Reset",
            "<a href='{{ reset_url }}'>click</a>",
        )
        bus = _bus(app)
        bus.publish(
            "user.password_reset",
            {
                "user_email": "eve@vbwd.test",
                "user_name": "Eve",
                "reset_url": "http://localhost/reset/abc",
            },
        )
        msg = _wait_for_message("eve@vbwd.test")
        assert msg is not None
        assert "http://localhost/reset/abc" in msg.get("HTML", "")


@requires_mailpit
class TestSubscriptionActivatedEmail:
    def test_email_delivered(self, app, db):
        _seed(
            app,
            db,
            "subscription.activated",
            "Welcome to {{ plan_name }}!",
            "<p>Plan: {{ plan_name }}</p>",
        )
        bus = _bus(app)
        bus.publish(
            "subscription.activated",
            {
                "user_email": "frank@vbwd.test",
                "user_name": "Frank",
                "plan_name": "Pro",
                "plan_price": "$49",
                "billing_period": "monthly",
                "start_date": "2026-03-16",
                "next_billing_date": "2026-04-16",
                "dashboard_url": "/dashboard",
            },
        )
        msg = _wait_for_message("frank@vbwd.test")
        assert msg is not None

    def test_plan_name_in_subject(self, app, db):
        _seed(
            app,
            db,
            "subscription.activated",
            "Subscribed to {{ plan_name }}",
            "<p>ok</p>",
        )
        bus = _bus(app)
        bus.publish(
            "subscription.activated",
            {
                "user_email": "grace@vbwd.test",
                "user_name": "Grace",
                "plan_name": "Enterprise",
            },
        )
        msg = _wait_for_message("grace@vbwd.test")
        assert msg is not None
        assert "Enterprise" in msg.get("Subject", "")


@requires_mailpit
class TestSubscriptionCancelledEmail:
    def test_email_delivered(self, app, db):
        _seed(
            app,
            db,
            "subscription.cancelled",
            "Subscription cancelled",
            "<p>Cancelled {{ plan_name }}</p>",
        )
        bus = _bus(app)
        bus.publish(
            "subscription.cancelled",
            {
                "user_email": "hal@vbwd.test",
                "user_name": "Hal",
                "plan_name": "Starter",
                "end_date": "2026-04-01",
            },
        )
        msg = _wait_for_message("hal@vbwd.test")
        assert msg is not None


@requires_mailpit
class TestSubscriptionExpiredEmail:
    def test_email_delivered(self, app, db):
        _seed(
            app,
            db,
            "subscription.expired",
            "Your subscription has expired",
            "<p>{{ plan_name }} expired</p>",
        )
        bus = _bus(app)
        bus.publish(
            "subscription.expired",
            {
                "user_email": "ida@vbwd.test",
                "user_name": "Ida",
                "plan_name": "Pro",
            },
        )
        msg = _wait_for_message("ida@vbwd.test")
        assert msg is not None


@requires_mailpit
class TestSubscriptionPaymentFailedEmail:
    def test_email_delivered(self, app, db):
        _seed(
            app,
            db,
            "subscription.payment_failed",
            "Payment failed for {{ plan_name }}",
            "<p>Retry soon</p>",
        )
        bus = _bus(app)
        bus.publish(
            "subscription.payment_failed",
            {
                "user_email": "jack@vbwd.test",
                "user_name": "Jack",
                "plan_name": "Pro",
                "amount": "$49",
                "next_attempt": "2026-03-20",
            },
        )
        msg = _wait_for_message("jack@vbwd.test")
        assert msg is not None


@requires_mailpit
class TestInvoiceCreatedEmail:
    def test_email_delivered(self, app, db):
        _seed(
            app,
            db,
            "invoice.created",
            "Invoice #{{ invoice_id }} created",
            "<p>Amount: {{ amount }}</p>",
        )
        bus = _bus(app)
        bus.publish(
            "invoice.created",
            {
                "user_email": "kate@vbwd.test",
                "user_name": "Kate",
                "invoice_id": "INV-001",
                "amount": "$49",
                "due_date": "2026-04-01",
            },
        )
        msg = _wait_for_message("kate@vbwd.test")
        assert msg is not None

    def test_invoice_id_in_subject(self, app, db):
        _seed(app, db, "invoice.created", "Invoice #{{ invoice_id }}", "<p>ok</p>")
        bus = _bus(app)
        bus.publish(
            "invoice.created",
            {
                "user_email": "leo@vbwd.test",
                "user_name": "Leo",
                "invoice_id": "INV-999",
            },
        )
        msg = _wait_for_message("leo@vbwd.test")
        assert msg is not None
        assert "INV-999" in msg.get("Subject", "")


@requires_mailpit
class TestInvoicePaidEmail:
    def test_email_delivered(self, app, db):
        _seed(
            app,
            db,
            "invoice.paid",
            "Payment received for #{{ invoice_id }}",
            "<p>Paid: {{ amount }}</p>",
        )
        bus = _bus(app)
        bus.publish(
            "invoice.paid",
            {
                "user_email": "mia@vbwd.test",
                "user_name": "Mia",
                "invoice_id": "INV-042",
                "amount": "$99",
                "paid_date": "2026-03-16",
            },
        )
        msg = _wait_for_message("mia@vbwd.test")
        assert msg is not None


@requires_mailpit
class TestContactFormEmail:
    def test_email_delivered_to_recipient(self, app, db):
        _seed(
            app,
            db,
            "contact_form.received",
            "New contact: {{ widget_slug }}",
            "<p>From: {{ fields | map(attribute='value') | join(', ') }}</p>",
            "Form: {{ widget_slug }}\n{{ fields_text }}",
        )
        bus = _bus(app)
        bus.publish(
            "contact_form.received",
            {
                "widget_slug": "contact-form",
                "recipient_email": "admin@vbwd.test",
                "remote_ip": "127.0.0.1",
                "fields": [
                    {"id": "name", "label": "Name", "value": "Nora"},
                    {"id": "email", "label": "Email", "value": "nora@vbwd.test"},
                    {"id": "field_1", "label": "Message", "value": "Hello team!"},
                ],
                "fields_text": "Name: Nora\nEmail: nora@vbwd.test\nMessage: Hello team!",
            },
        )
        msg = _wait_for_message("admin@vbwd.test")
        assert msg is not None, "Contact form notification not received by admin"

    def test_subject_contains_widget_slug(self, app, db):
        _seed(
            app,
            db,
            "contact_form.received",
            "Contact via {{ widget_slug }}",
            "<p>ok</p>",
        )
        bus = _bus(app)
        bus.publish(
            "contact_form.received",
            {
                "recipient_email": "support@vbwd.test",
                "widget_slug": "my-form",
                "fields": [],
                "fields_text": "",
                "remote_ip": "1.2.3.4",
            },
        )
        msg = _wait_for_message("support@vbwd.test")
        assert msg is not None
        assert "my-form" in msg.get("Subject", "")

    def test_no_email_when_recipient_empty(self, app, db):
        """Empty recipient_email → handler skips send silently."""
        _seed(app, db, "contact_form.received", "Subject", "<p>body</p>")
        bus = _bus(app)
        bus.publish(
            "contact_form.received",
            {
                "recipient_email": "",
                "widget_slug": "silent-form",
                "fields": [],
                "fields_text": "",
                "remote_ip": "1.2.3.4",
            },
        )
        # Give a short window; no message should arrive
        msg = _wait_for_message("", timeout=1.5)
        assert msg is None, "Email was sent despite empty recipient"

    def test_text_body_contains_fields(self, app, db):
        _seed(
            app,
            db,
            "contact_form.received",
            "New message",
            "<p>ok</p>",
            "{{ fields_text }}",
        )
        bus = _bus(app)
        bus.publish(
            "contact_form.received",
            {
                "recipient_email": "ops@vbwd.test",
                "widget_slug": "cf",
                "fields": [{"id": "name", "label": "Name", "value": "Oscar"}],
                "fields_text": "Name: Oscar",
                "remote_ip": "10.0.0.1",
            },
        )
        msg = _wait_for_message("ops@vbwd.test")
        assert msg is not None
        # Mailpit exposes plain text body in the "Text" key
        assert "Oscar" in msg.get("Text", "") or "Oscar" in msg.get("HTML", "")


@requires_mailpit
class TestSubscriptionRenewedEmail:
    def test_email_delivered(self, app, db):
        _seed(
            app,
            db,
            "subscription.renewed",
            "Subscription renewed — {{ plan_name }}",
            "<p>Renewed {{ plan_name }}</p>",
        )
        bus = _bus(app)
        bus.publish(
            "subscription.renewed",
            {
                "user_email": "pat@vbwd.test",
                "user_name": "Pat",
                "plan_name": "Pro",
                "plan_price": "$49",
                "billing_period": "monthly",
                "next_billing_date": "2026-05-16",
                "dashboard_url": "/dashboard",
            },
        )
        msg = _wait_for_message("pat@vbwd.test")
        assert msg is not None

    def test_plan_name_in_subject(self, app, db):
        _seed(app, db, "subscription.renewed", "Renewed: {{ plan_name }}", "<p>ok</p>")
        bus = _bus(app)
        bus.publish(
            "subscription.renewed",
            {
                "user_email": "quinn@vbwd.test",
                "user_name": "Quinn",
                "plan_name": "Starter",
            },
        )
        msg = _wait_for_message("quinn@vbwd.test")
        assert msg is not None
        assert "Starter" in msg.get("Subject", "")
