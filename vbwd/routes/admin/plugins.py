"""Admin plugin management routes."""
import logging
from flask import Blueprint, jsonify, request, current_app
from vbwd.middleware.auth import require_auth, require_admin, require_permission
from vbwd.plugins.base import PluginStatus

logger = logging.getLogger(__name__)

admin_plugins_bp = Blueprint(
    "admin_plugins", __name__, url_prefix="/api/v1/admin/plugins"
)


def _get_persisted_status(plugin_name):
    """Read plugin status from config_store (shared JSON file, source of truth)."""
    config_store = getattr(current_app, "config_store", None)
    if config_store:
        entry = config_store.get_by_name(plugin_name)
        if entry:
            return "active" if entry.status == "enabled" else "inactive"
    return "inactive"


def _sync_in_memory(plugin, target_enabled):
    """Best-effort sync of in-memory plugin state to match persisted state."""
    try:
        if target_enabled:
            if plugin.status != PluginStatus.ENABLED:
                if plugin.status != PluginStatus.INITIALIZED:
                    plugin.initialize(plugin._config)
                plugin.enable()
        else:
            if plugin.status == PluginStatus.ENABLED:
                plugin.disable()
            elif plugin.status != PluginStatus.DISABLED:
                plugin._status = PluginStatus.DISABLED
    except Exception as e:
        logger.warning(f"In-memory sync failed for '{plugin.metadata.name}': {e}")


def _prepare_admin_config(admin_config: dict) -> dict:
    """Prepare admin config by adding id to tabs, key to fields, and component type."""
    if admin_config.get("tabs"):
        for idx, tab in enumerate(admin_config["tabs"]):
            if "id" not in tab:
                tab["id"] = f"tab-{idx}"
            if "fields" in tab:
                for field in tab["fields"]:
                    # Add key from name if not present
                    if "key" not in field and "name" in field:
                        field["key"] = field["name"]

                    # Derive component type from field type if not present
                    if "component" not in field:
                        field_type = field.get("type", "text").lower()
                        if field_type == "boolean":
                            field["component"] = "checkbox"
                        elif field_type == "number":
                            field["component"] = "input"
                            field["inputType"] = "number"
                        elif field_type == "select":
                            field["component"] = "select"
                        elif field_type == "textarea":
                            field["component"] = "textarea"
                        else:  # text, string, etc.
                            field["component"] = "input"
                            field["inputType"] = "text"
    return admin_config


@admin_plugins_bp.route("", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.view")
def list_plugins():
    """List all backend plugins with their status."""
    plugin_manager = getattr(current_app, "plugin_manager", None)
    if not plugin_manager:
        return jsonify({"error": "Plugin system not available"}), 500

    schema_reader = getattr(current_app, "schema_reader", None)

    plugins = []
    for plugin in plugin_manager.get_all_plugins():
        meta = plugin.metadata
        status = _get_persisted_status(meta.name)

        has_config = False
        if schema_reader:
            admin_config = schema_reader.get_admin_config(meta.name)
            has_config = bool(admin_config.get("tabs"))

        plugins.append(
            {
                "name": meta.name,
                "version": meta.version,
                "author": meta.author,
                "description": meta.description,
                "status": status,
                "dependencies": meta.dependencies or [],
                "hasConfig": has_config,
            }
        )

    return jsonify({"plugins": plugins}), 200


@admin_plugins_bp.route("/<plugin_name>", methods=["GET"])
@require_auth
@require_admin
@require_permission("settings.view")
def get_plugin_detail(plugin_name):
    """Get detailed plugin info including config schema and admin config."""
    plugin_manager = getattr(current_app, "plugin_manager", None)
    if not plugin_manager:
        return jsonify({"error": "Plugin system not available"}), 500

    plugin = plugin_manager.get_plugin(plugin_name)
    if not plugin:
        return jsonify({"error": f"Plugin '{plugin_name}' not found"}), 404

    meta = plugin.metadata
    status = _get_persisted_status(plugin_name)

    config_schema = {}
    admin_config = {}
    saved_config = {}

    schema_reader = getattr(current_app, "schema_reader", None)
    if schema_reader:
        config_schema = schema_reader.get_config_schema(plugin_name)
        admin_config = schema_reader.get_admin_config(plugin_name)
        admin_config = _prepare_admin_config(admin_config)

    config_store = getattr(current_app, "config_store", None)
    if config_store:
        saved_config = config_store.get_config(plugin_name)

    return (
        jsonify(
            {
                "name": meta.name,
                "version": meta.version,
                "author": meta.author,
                "description": meta.description,
                "status": status,
                "dependencies": meta.dependencies or [],
                "configSchema": config_schema,
                "adminConfig": admin_config,
                "savedConfig": saved_config,
            }
        ),
        200,
    )


@admin_plugins_bp.route("/<plugin_name>/config", methods=["PUT"])
@require_auth
@require_admin
@require_permission("settings.system")
def save_plugin_config(plugin_name):
    """Save plugin configuration values."""
    plugin_manager = getattr(current_app, "plugin_manager", None)
    if not plugin_manager:
        return jsonify({"error": "Plugin system not available"}), 500

    plugin = plugin_manager.get_plugin(plugin_name)
    if not plugin:
        return jsonify({"error": f"Plugin '{plugin_name}' not found"}), 404

    config_store = getattr(current_app, "config_store", None)
    if not config_store:
        return jsonify({"error": "Config store not available"}), 500

    config_values = request.get_json(silent=True) or {}
    config_store.save_config(plugin_name, config_values)

    return jsonify({"message": "Configuration saved", "config": config_values}), 200


@admin_plugins_bp.route("/<plugin_name>/enable", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.system")
def enable_plugin(plugin_name):
    """Enable a backend plugin."""
    plugin_manager = getattr(current_app, "plugin_manager", None)
    if not plugin_manager:
        return jsonify({"error": "Plugin system not available"}), 500

    plugin = plugin_manager.get_plugin(plugin_name)
    if not plugin:
        return jsonify({"error": f"Plugin '{plugin_name}' not found"}), 404

    # Persist to config_store (source of truth, shared across workers)
    config_store = getattr(current_app, "config_store", None)
    if config_store:
        config_store.save(plugin_name, "enabled", plugin._config)

    # Best-effort in-memory sync for this worker
    _sync_in_memory(plugin, target_enabled=True)

    return jsonify({"message": "Plugin enabled", "status": "enabled"}), 200


@admin_plugins_bp.route("/<plugin_name>/disable", methods=["POST"])
@require_auth
@require_admin
@require_permission("settings.system")
def disable_plugin(plugin_name):
    """Disable a backend plugin."""
    plugin_manager = getattr(current_app, "plugin_manager", None)
    if not plugin_manager:
        return jsonify({"error": "Plugin system not available"}), 500

    plugin = plugin_manager.get_plugin(plugin_name)
    if not plugin:
        return jsonify({"error": f"Plugin '{plugin_name}' not found"}), 404

    # Persist to config_store (source of truth, shared across workers)
    config_store = getattr(current_app, "config_store", None)
    if config_store:
        config_store.save(plugin_name, "disabled", plugin._config)

    # Best-effort in-memory sync for this worker
    _sync_in_memory(plugin, target_enabled=False)

    return jsonify({"message": "Plugin disabled", "status": "disabled"}), 200
