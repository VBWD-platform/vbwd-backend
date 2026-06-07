"""Generic on-disk location for editable/runtime assets.

Assets that are edited or generated per deployment (and therefore must persist
across image rebuilds via a host mount, never baked into the image) live under
``${VBWD_VAR_DIR:-/app/var}/assets/<owner>/...``. ``owner`` is ``"core"`` for
core-owned assets or a plugin id for plugin-owned assets (e.g. a plugin calls
``asset_dir("<plugin_id>", "media")``).

This is generic core infrastructure: it knows nothing about any domain or
plugin and imports nothing from ``plugins``.
"""
import os

DEFAULT_VAR_DIR = "/app/var"
ASSETS_SUBDIR = "assets"


def asset_dir(owner: str, *parts: str) -> str:
    """Resolve the directory holding ``owner``'s assets under the var dir.

    Args:
        owner: ``"core"`` or a plugin id; namespaces the asset tree.
        *parts: Optional path segments beneath the owner namespace.

    Returns:
        Absolute path ``${VBWD_VAR_DIR}/assets/<owner>/<parts...>``.
    """
    var_dir = os.environ.get("VBWD_VAR_DIR", DEFAULT_VAR_DIR)
    return os.path.join(var_dir, ASSETS_SUBDIR, owner, *parts)
