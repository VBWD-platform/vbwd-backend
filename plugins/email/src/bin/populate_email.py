#!/usr/bin/env python3
"""
Populate the email_template table with default transactional email templates.

Creates one template per event type using UPSERT logic — existing records
(matched by event_type) are skipped; only missing ones are inserted.
Safe to re-run at any time.

Event types seeded:
  - subscription.activated
  - subscription.cancelled
  - subscription.payment_failed
  - subscription.renewed
  - trial.started
  - trial.expiring_soon
  - user.registered
  - user.password_reset

Usage:
    python /app/plugins/email/src/bin/populate_email.py
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from plugins.email.src.seeds import DEFAULT_TEMPLATES, seed_default_templates  # noqa: E402


def populate_email() -> None:
    from src.extensions import db  # noqa: E402
    from plugins.email.src.models.email_template import EmailTemplate  # noqa: E402

    created = seed_default_templates(db.session)
    total = len(DEFAULT_TEMPLATES)
    skipped = total - created

    print()
    print("=" * 50)
    print("✓ Email templates population complete")
    print(f"  Created : {created}")
    print(f"  Skipped : {skipped} (already exist)")
    print(f"  Total   : {total} templates")
    print()
    for tpl in DEFAULT_TEMPLATES:
        status = "+" if skipped < total else "="
        print(f"  {status} {tpl['event_type']}")
    print("=" * 50)
    print()
    print("  Admin: http://localhost:8081/admin/email/templates")
    print()


if __name__ == "__main__":
    from src.app import create_app

    app = create_app()
    with app.app_context():
        populate_email()
