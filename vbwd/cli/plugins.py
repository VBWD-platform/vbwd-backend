"""Plugin management CLI commands."""
import click
from flask import current_app
from flask.cli import with_appcontext

from vbwd.plugins.errors import PluginDependencyError


@click.group("plugins")
def plugins_cli():
    """Plugin management commands."""
    pass


def _unmet_dependency_note(manager, plugin) -> str:
    """Return a ' — needs <dep><spec> (have <ver>)' note for unmet deps, else ''."""
    unmet = [
        descriptor
        for descriptor in manager.dependency_resolver.describe(
            plugin, manager.get_plugin
        )
        if not descriptor["satisfied"]
    ]
    if not unmet:
        return ""
    notes = ", ".join(
        f"needs {descriptor['name']}{descriptor['specifier']} "
        f"(have {descriptor['installed_version'] or 'missing'})"
        for descriptor in unmet
    )
    return f" — {notes}"


@plugins_cli.command("list")
@with_appcontext
def list_plugins():
    """List all registered plugins."""
    manager = getattr(current_app, "plugin_manager", None)
    if not manager:
        click.echo("Plugin system not initialized.")
        return

    plugins = manager.get_all_plugins()
    if not plugins:
        click.echo("No plugins registered.")
        return

    for plugin in plugins:
        meta = plugin.metadata
        line = f"{meta.name} ({meta.version}) — {plugin.status.value.upper()}"
        line += _unmet_dependency_note(manager, plugin)
        click.echo(line)


@plugins_cli.command("enable")
@click.argument("name")
@with_appcontext
def enable_plugin(name):
    """Enable a plugin."""
    manager = getattr(current_app, "plugin_manager", None)
    if not manager:
        click.echo("Plugin system not initialized.")
        return

    try:
        plugin = manager.get_plugin(name)
        if not plugin:
            click.echo(f"Plugin '{name}' not found.")
            return
        if plugin.status.value == "enabled":
            click.echo(f"Plugin '{name}' is already enabled.")
            return
        # Re-initialize if needed
        from vbwd.plugins.base import PluginStatus

        if plugin.status == PluginStatus.DISABLED:
            plugin._status = PluginStatus.INITIALIZED
        manager.enable_plugin(name)
        click.echo(f"Plugin '{name}' enabled.")
    except PluginDependencyError as dependency_error:
        # Distinct from a generic failure: print the version-specific reason
        # and exit non-zero (ClickException writes "Error: ..." to stderr).
        raise click.ClickException(str(dependency_error))
    except ValueError as e:
        click.echo(f"Error: {e}")


@plugins_cli.command("disable")
@click.argument("name")
@with_appcontext
def disable_plugin(name):
    """Disable a plugin."""
    manager = getattr(current_app, "plugin_manager", None)
    if not manager:
        click.echo("Plugin system not initialized.")
        return

    try:
        manager.disable_plugin(name)
        click.echo(f"Plugin '{name}' disabled.")
    except ValueError as e:
        click.echo(f"Error: {e}")
