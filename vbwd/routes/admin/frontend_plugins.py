"""Admin endpoints for managing frontend-plugin manifests.

The fe-admin and fe-user apps each read a ``plugins.json`` that declares
which plugins are loaded by their respective SPA. The authoritative copy
of those manifests lives OUTSIDE every container, in a shared ``VAR_DIR``
that all three containers (api / fe-admin / fe-user) bind-mount. This
removes the old per-browser localStorage hack, avoids duplicating a
build-time manifest next to a runtime one, and lets the backend be the
single writer while the frontends stay read-only.

Canonical layout under ``${VAR_DIR}/plugins/``::

    backend-plugins.json
    backend-plugins-config.json
    fe-admin-plugins.json
    fe-admin-plugins-config.json
    fe-user-plugins.json
    fe-user-plugins-config.json

The admin API exposes ``POST /api/v1/admin/frontend-plugins/<app>/
<plugin>/{enable,disable}`` which rewrites the matching file in place.
The path per (app, kind) is resolved from environment variables set by
the instance's compose file — missing env var → the app is considered
unmanaged (404) rather than crashing.
"""
import json
import os

from flask import Blueprint, jsonify

from vbwd.middleware.auth import require_admin, require_auth, require_permission

frontend_plugins_bp = Blueprint(
    "admin_frontend_plugins", __name__, url_prefix="/api/v1/admin/frontend-plugins"
)


def _default_manifest_paths() -> dict[str, str]:
    """Map app slug → manifest file path, from env vars.

    Only apps with a configured env var are considered manageable. This
    lets deployments opt into server-side plugin management per app and
    keeps the endpoint a clean 404 when a deployment chose not to mount
    a particular manifest into the backend.
    """
    env_map = {
        "admin": os.environ.get("VBWD_FE_ADMIN_PLUGINS_JSON"),
        "user": os.environ.get("VBWD_FE_USER_PLUGINS_JSON"),
        "backend": os.environ.get("VBWD_BACKEND_PLUGINS_JSON"),
    }
    return {app: path for app, path in env_map.items() if path}


MANIFEST_PATHS: dict[str, str] = _default_manifest_paths()


def _resolve_manifest_path(app: str) -> str | None:
    """Return the manifest file for the given app, or None if unknown."""
    return MANIFEST_PATHS.get(app)


def _read_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_manifest(path: str, manifest: dict) -> None:
    # Write in-place (no tempfile+rename) because manifests are bind-
    # mounted single files in prod compose — rename across inodes fails
    # with "Device or resource busy".
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")


@frontend_plugins_bp.route("/<app>", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.system")
def get_frontend_manifest(app: str):
    """Return the parsed manifest for a frontend app."""
    path = _resolve_manifest_path(app)
    if not path:
        return (
            jsonify(
                {
                    "error": f"Unknown or unconfigured frontend app: '{app}'",
                    "configured_apps": sorted(MANIFEST_PATHS.keys()),
                }
            ),
            404,
        )
    return jsonify(_read_manifest(path)), 200


def _set_enabled(app: str, plugin_name: str, enabled: bool):
    path = _resolve_manifest_path(app)
    if not path:
        return (
            jsonify(
                {
                    "error": f"Unknown or unconfigured frontend app: '{app}'",
                    "configured_apps": sorted(MANIFEST_PATHS.keys()),
                }
            ),
            404,
        )

    manifest = _read_manifest(path)
    plugins = manifest.get("plugins") or {}
    if plugin_name not in plugins:
        return (
            jsonify(
                {
                    "error": (
                        f"Plugin '{plugin_name}' is not in the '{app}' manifest. "
                        "Add it to plugins.json before toggling."
                    )
                }
            ),
            404,
        )

    plugins[plugin_name]["enabled"] = enabled
    manifest["plugins"] = plugins

    _write_manifest(path, manifest)

    return (
        jsonify(
            {
                "app": app,
                "plugin": plugin_name,
                "enabled": enabled,
                "updated_path": path,
            }
        ),
        200,
    )


@frontend_plugins_bp.route("/<app>/<plugin_name>/enable", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.system")
def enable_frontend_plugin(app: str, plugin_name: str):
    return _set_enabled(app, plugin_name, True)


@frontend_plugins_bp.route("/<app>/<plugin_name>/disable", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.system")
def disable_frontend_plugin(app: str, plugin_name: str):
    return _set_enabled(app, plugin_name, False)
