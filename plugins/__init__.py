"""User-created plugins directory.

This is a *namespace* package. ``pkgutil.extend_path`` merges every ``plugins/``
directory found on ``sys.path`` into a single ``plugins.__path__`` — so a plugin
cloned into this local tree AND a plugin ``pip install``ed as
``vbwd-plugin-<name>`` (which lands in ``site-packages/plugins/<name>/``) are both
importable as ``plugins.<name>``. Discovery (PluginManager, Alembic env) iterates
``plugins.__path__`` and therefore sees clone-based and pip-installed plugins
identically.
"""

__path__ = __import__("pkgutil").extend_path(__path__, __name__)
