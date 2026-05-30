"""CLI command to seed the default billing-address countries.

Ungated (NOT behind TEST_DATA_SEED) — the country catalog is foundational
reference data on every instance, prod included. Idempotent: safe to run on
every deploy after ``flask db upgrade``.
"""
import click
from flask.cli import with_appcontext


@click.command("seed-countries")
@with_appcontext
def seed_countries_command():
    """
    Seed the default billing-address country catalog. Idempotent — re-running
    creates nothing new (existing enable/disable edits are preserved).

    Usage:
        flask seed-countries
    """
    from vbwd.extensions import db
    from vbwd.services.country_seeder import seed_countries

    result = seed_countries(db.session)

    click.echo("Country seed complete:")
    click.echo(f"  countries created: {result.created}")
    click.echo(f"  enabled (default): {result.enabled_count}")
