"""CLI command to seed the baseline payment methods.

Ungated (NOT behind TEST_DATA_SEED) — the manual ``invoice`` method is
foundational reference data on every instance, prod included. Idempotent: safe
to run on every deploy after ``flask db upgrade``.
"""
import click
from flask.cli import with_appcontext


@click.command("seed-payment-methods")
@with_appcontext
def seed_payment_methods_command():
    """
    Seed the baseline payment-method catalog (the manual ``invoice`` method).
    Idempotent — re-running creates nothing new (operator edits are preserved).

    Usage:
        flask seed-payment-methods
    """
    from vbwd.extensions import db
    from vbwd.services.payment_method_seeder import seed_payment_methods

    result = seed_payment_methods(db.session)

    click.echo("Payment-method seed complete:")
    click.echo(f"  methods created: {result.created}")
