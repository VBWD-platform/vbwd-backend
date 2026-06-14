"""CLI command to seed the default German VAT taxes.

Ungated (NOT behind TEST_DATA_SEED) — German VAT is foundational tax
reference data on every instance, prod included. Idempotent: safe to run on
every deploy after ``flask db upgrade``.
"""
import click
from flask.cli import with_appcontext


@click.command("seed-taxes")
@with_appcontext
def seed_taxes_command():
    """
    Seed the default German VAT tax catalog. Idempotent — re-running creates
    nothing new (existing operator edits are preserved).

    Usage:
        flask seed-taxes
    """
    from vbwd.extensions import db
    from vbwd.services.tax_seeder import seed_taxes

    result = seed_taxes(db.session)

    click.echo("Tax seed complete:")
    click.echo(f"  taxes created: {result.taxes_created}")
