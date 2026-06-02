"""``flask seed [PLUGIN_NAME]...`` — orchestrate per-plugin demo seeding (S30).

Replaces the ad-hoc ``for p in ...; python plugins/$p/populate_db.py || true``
shell loop that silently swallowed failures. This command:

- discovers enabled plugins via the plugin manager (DI / agnostic — core never
  imports a specific plugin), so a half-installed deploy can't crash it;
- calls each plugin's optional ``populate()`` method, falling back to running
  its ``populate_db.py`` module when absent — but WITH exit-code propagation;
- writes a seed marker on success so ``/api/v1/_seed_status`` can report it;
- fails the command on the first plugin error in ``--strict`` (default), or
  continues and reports at the end in ``--best-effort``.

Each plugin's seed is expected to be idempotent — running ``seed all`` twice
creates nothing the second time.
"""
import json
import os
import runpy
import sys
from typing import Any, Dict, List, Optional

import click
from flask import current_app
from flask.cli import with_appcontext

from vbwd.extensions import db
from vbwd.repositories.seed_marker_repository import SeedMarkerRepository

# Exit codes (documented in the sprint contract).
EXIT_OK = 0
EXIT_PLUGIN_ERROR = 1
EXIT_UNKNOWN_PLUGIN = 2


def write_seed_marker(plugin_name: str) -> None:
    """Persist a successful-seed marker for ``plugin_name``."""
    SeedMarkerRepository(db.session).upsert(plugin_name)
    db.session.commit()


def clear_seed_marker(plugin_name: str) -> None:
    """Remove the seed marker for ``plugin_name`` (``--reset``)."""
    SeedMarkerRepository(db.session).clear(plugin_name)
    db.session.commit()


# Sentinel returned by the fallback when a plugin has neither a populate()
# method nor a populate_db.py — it simply ships no demo data, which is a
# no-op success, not an error (so ``seed all`` in strict mode still passes).
NO_SEED_SOURCE = -1


def run_populate_db_module(plugin_name: str) -> int:
    """Run a plugin's ``populate_db.py`` as a module, returning its exit code.

    The legacy fallback for plugins that have not adopted ``populate()``.
    Unlike the old shell loop, a non-zero ``sys.exit`` / raised SystemExit is
    propagated rather than swallowed by ``|| true``. Returns ``NO_SEED_SOURCE``
    when the plugin has no ``populate_db.py`` at all (nothing to seed).
    """
    plugins_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "plugins"
    )
    script_path = os.path.join(plugins_root, plugin_name, "populate_db.py")
    if not os.path.exists(script_path):
        return NO_SEED_SOURCE
    try:
        runpy.run_path(script_path, run_name="__main__")
    except SystemExit as exit_signal:
        code = exit_signal.code
        return int(code) if isinstance(code, int) else (0 if code is None else 1)
    return 0


def _resolve_plugin_names(plugin_arguments: List[str]) -> List[str]:
    """Map CLI arguments to the concrete enabled-plugin names to seed.

    ``all`` (or no argument) expands to every enabled plugin. Named plugins
    are validated against the manager; an unknown name aborts with exit 2.
    """
    plugin_manager = getattr(current_app, "plugin_manager")
    enabled = [plugin.metadata.name for plugin in plugin_manager.get_enabled_plugins()]

    if not plugin_arguments or list(plugin_arguments) == ["all"]:
        return enabled

    resolved: List[str] = []
    for name in plugin_arguments:
        if plugin_manager.get_plugin(name) is None:
            click.echo(f"Error: unknown plugin '{name}'", err=True)
            sys.exit(EXIT_UNKNOWN_PLUGIN)
        resolved.append(name)
    return resolved


def _seed_one_plugin(plugin_name: str) -> Dict[str, Any]:
    """Seed a single plugin; return a result entry for the JSON summary.

    Never raises — captures any failure into ``errors`` so the caller decides
    strict-vs-best-effort. ``ok`` is True only when the seed completed and the
    marker was written.
    """
    entry: Dict[str, Any] = {
        "name": plugin_name,
        "ok": False,
        "created": 0,
        "errors": [],
    }
    plugin_manager = getattr(current_app, "plugin_manager")
    plugin = plugin_manager.get_plugin(plugin_name)
    try:
        populate = getattr(plugin, "populate", None)
        if callable(populate):
            result = populate() or {}
            entry["created"] = int(result.get("created", 0))
            plugin_errors = result.get("errors") or []
            if plugin_errors:
                entry["errors"] = list(plugin_errors)
                return entry
        else:
            exit_code = run_populate_db_module(plugin_name)
            if exit_code not in (0, NO_SEED_SOURCE):
                entry["errors"] = [f"populate_db.py exited with code {exit_code}"]
                return entry
        write_seed_marker(plugin_name)
        entry["ok"] = True
    except Exception as error:
        # Boundary catch by design: a failing plugin must become a result
        # entry so the caller applies the strict / best-effort policy. The
        # error is recorded (never swallowed) and surfaces in the summary.
        entry["errors"] = [str(error)]
    return entry


def _emit_human_summary(results: List[Dict[str, Any]]) -> None:
    """Print a readable per-plugin summary to stdout."""
    for entry in results:
        if entry["ok"]:
            click.echo(f"  {entry['name']}: created={entry['created']}")
        else:
            joined = "; ".join(entry["errors"]) or "unknown error"
            click.echo(f"  {entry['name']}: FAILED — {joined}")


@click.command("seed")
@click.argument("plugin_name", nargs=-1)
@click.option(
    "--strict/--best-effort",
    "strict",
    default=True,
    help="Fail on the first plugin error (default), or continue and report.",
)
@click.option(
    "--json", "as_json", is_flag=True, help="Emit a machine-readable summary."
)
@click.option("--reset", is_flag=True, help="Clear seed markers instead of seeding.")
@with_appcontext
def seed_command(plugin_name, strict, as_json, reset):
    """Seed demo data for one, several, or all enabled plugins.

    Examples:
        flask seed all
        flask seed meinchat subscription
        flask seed all --best-effort --json
        flask seed meinchat --reset
    """
    names = _resolve_plugin_names(list(plugin_name))

    if reset:
        for name in names:
            clear_seed_marker(name)
        if not as_json:
            click.echo(f"Cleared seed markers: {', '.join(names) or '(none)'}")
        else:
            click.echo(json.dumps({"reset": names}))
        sys.exit(EXIT_OK)

    results: List[Dict[str, Any]] = []
    failed: Optional[str] = None
    for name in names:
        entry = _seed_one_plugin(name)
        results.append(entry)
        if not entry["ok"]:
            failed = name
            if strict:
                break

    if as_json:
        click.echo(json.dumps({"plugins": results}))
    else:
        click.echo("Seed complete:")
        _emit_human_summary(results)

    if failed is not None and strict:
        if not as_json:
            click.echo(f"Seeding failed for plugin '{failed}'", err=True)
        sys.exit(EXIT_PLUGIN_ERROR)
    sys.exit(EXIT_OK)
