"""CLI command to seed the default RBAC roles + permissions.

Ungated (NOT behind TEST_DATA_SEED) — default roles + permissions are
foundational data on every instance, prod included. Idempotent: safe to run
on every deploy after ``flask db upgrade``.
"""
import click
from flask import current_app
from flask.cli import with_appcontext


@click.command("seed-rbac")
@with_appcontext
def seed_rbac_command():
    """
    Seed the default RBAC roles (super_admin, admin, user) and sync the
    permission catalog. Idempotent — re-running creates nothing new.

    Usage:
        flask seed-rbac
    """
    from vbwd.extensions import db
    from vbwd.services.rbac_seeder import seed_default_rbac

    plugin_manager = getattr(current_app, "plugin_manager", None)
    result = seed_default_rbac(db.session, plugin_manager=plugin_manager)

    click.echo("RBAC seed complete:")
    click.echo(f"  roles created:              {result.roles_created}")
    click.echo(f"  roles updated:              {result.roles_updated}")
    click.echo(f"  permissions created:        {result.permissions_created}")
    click.echo(f"  user access levels created: {result.user_access_levels_created}")
