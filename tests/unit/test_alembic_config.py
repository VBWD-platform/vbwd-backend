"""S02 oracle — alembic.ini must register every plugin migration directory.

Any plugin whose ``plugins/<name>/migrations/versions/`` directory contains
real migration files (anything other than ``__init__.py``) MUST be listed in
``alembic.ini``'s ``version_locations``. Otherwise ``alembic upgrade heads``
silently skips those revisions and prod runs against an under-migrated DB.

Plus a guard against the ``head`` vs ``heads`` foot-gun in ``Makefile.server``
— with multiple plugin branches the singular form is undefined and only
upgrades one branch.
"""
import configparser
import os
import re


def _backend_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def _plugin_dirs_with_migrations() -> list[str]:
    """Return ``plugins/<name>/migrations/versions`` for every plugin that
    actually ships migration files (ignoring ``__init__.py``)."""
    plugins_root = os.path.join(_backend_root(), "plugins")
    dirs: list[str] = []
    for plugin_name in sorted(os.listdir(plugins_root)):
        versions_dir = os.path.join(plugins_root, plugin_name, "migrations", "versions")
        if not os.path.isdir(versions_dir):
            continue
        migration_files = [
            file_name
            for file_name in os.listdir(versions_dir)
            if file_name.endswith(".py") and file_name != "__init__.py"
        ]
        if migration_files:
            dirs.append(f"plugins/{plugin_name}/migrations/versions")
    return dirs


def _alembic_version_locations() -> str:
    """The raw ``version_locations`` value from alembic.ini.

    Disables interpolation because alembic.ini uses ``%(here)s`` which is
    alembic-specific (resolved by alembic itself, not configparser).
    """
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(os.path.join(_backend_root(), "alembic.ini"))
    return parser["alembic"]["version_locations"]


def test_every_plugin_with_migrations_is_registered_in_alembic_ini():
    """The exit gate: every plugin migration dir is discoverable by alembic."""
    locations = _alembic_version_locations()
    missing: list[str] = []
    for plugin_dir in _plugin_dirs_with_migrations():
        if plugin_dir not in locations:
            missing.append(plugin_dir)
    assert not missing, (
        "alembic.ini version_locations is missing plugin migration dir(s):\n  - "
        + "\n  - ".join(missing)
        + "\nWithout these, `alembic upgrade heads` silently skips those "
        "revisions — environments with these plugins enabled will run on an "
        "under-migrated schema."
    )


def test_makefile_server_uses_alembic_upgrade_heads_plural():
    """``head`` (singular) is undefined with multiple branches; only one
    head gets upgraded and the others silently stay behind."""
    with open(os.path.join(_backend_root(), "Makefile.server")) as handle:
        content = handle.read()
    # any `alembic upgrade head` not followed by 's' is a bug
    offenders = re.findall(r"alembic upgrade head(?!s)", content)
    assert not offenders, (
        f"Makefile.server uses `alembic upgrade head` (singular) "
        f"{len(offenders)} time(s); must be `alembic upgrade heads` so all "
        "plugin migration branches advance together."
    )
