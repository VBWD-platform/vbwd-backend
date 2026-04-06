"""Admin access management routes — roles, permissions, user-role assignment."""
from uuid import uuid4

from flask import Blueprint, jsonify, request
from vbwd.extensions import db
from vbwd.middleware.auth import require_auth, require_permission
from vbwd.models.role import Role, Permission, user_roles
from vbwd.models.user import User

access_bp = Blueprint("admin_access", __name__, url_prefix="/api/v1/admin/access")


# ── Core permissions (always available) ─────────────────────────────────

CORE_PERMISSIONS = [
    {"key": "users.view", "label": "View users", "group": "Users"},
    {"key": "users.manage", "label": "Manage users", "group": "Users"},
    {"key": "invoices.view", "label": "View invoices", "group": "Invoices"},
    {"key": "invoices.manage", "label": "Manage invoices", "group": "Invoices"},
    {"key": "analytics.view", "label": "View analytics", "group": "Analytics"},
    {"key": "settings.view", "label": "View settings", "group": "Settings"},
    {"key": "settings.manage", "label": "Manage settings", "group": "Settings"},
    {
        "key": "settings.system",
        "label": "System settings (payment providers, API keys)",
        "group": "Settings",
    },
]


def _get_all_permissions():
    """Collect permissions from core + all enabled plugins."""
    from flask import current_app

    result = {"core": CORE_PERMISSIONS}

    manager = getattr(current_app, "plugin_manager", None)
    if manager:
        for plugin in manager.get_enabled_plugins():
            admin_perms = getattr(plugin, "admin_permissions", None)
            if admin_perms:
                result[plugin.metadata.name] = admin_perms

    return result


# ── Access Levels (Roles) ───────────────────────────────────────────────


@access_bp.route("/levels", methods=["GET"])
@require_auth
@require_permission("settings.system")
def list_levels():
    """List all access levels (roles) with permissions."""
    roles = db.session.query(Role).order_by(Role.is_system.desc(), Role.name).all()
    return jsonify({"levels": [r.to_dict() for r in roles]}), 200


@access_bp.route("/levels", methods=["POST"])
@require_auth
@require_permission("settings.system")
def create_level():
    """Create a new access level (role)."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    slug = data.get("slug") or name.lower().replace(" ", "-")
    if db.session.query(Role).filter_by(slug=slug).first():
        return jsonify({"error": f"Role '{slug}' already exists"}), 400

    role = Role(
        id=uuid4(),
        name=name,
        slug=slug,
        description=data.get("description", ""),
        is_system=False,
    )

    # Assign permissions
    permission_keys = data.get("permissions", [])
    _assign_permissions(role, permission_keys)

    db.session.add(role)
    db.session.commit()
    return jsonify({"level": role.to_dict()}), 201


@access_bp.route("/levels/<level_id>", methods=["GET"])
@require_auth
@require_permission("settings.system")
def get_level(level_id):
    """Get access level detail with assigned users."""
    role = db.session.query(Role).filter_by(id=level_id).first()
    if not role:
        return jsonify({"error": "Access level not found"}), 404

    result = role.to_dict()
    result["users"] = [
        {"id": str(u.id), "email": u.email, "name": u.to_dict().get("name")}
        for u in role.users.all()
    ]
    return jsonify({"level": result}), 200


@access_bp.route("/levels/<level_id>", methods=["PUT"])
@require_auth
@require_permission("settings.system")
def update_level(level_id):
    """Update an access level (role) and its permissions."""
    role = db.session.query(Role).filter_by(id=level_id).first()
    if not role:
        return jsonify({"error": "Access level not found"}), 404

    data = request.get_json() or {}

    if "name" in data:
        role.name = data["name"]
    if "slug" in data and data["slug"] != role.slug:
        if db.session.query(Role).filter_by(slug=data["slug"]).first():
            return jsonify({"error": f"Slug '{data['slug']}' already exists"}), 400
        role.slug = data["slug"]
    if "description" in data:
        role.description = data["description"]
    if "permissions" in data:
        _assign_permissions(role, data["permissions"])

    db.session.commit()
    return jsonify({"level": role.to_dict()}), 200


@access_bp.route("/levels/<level_id>", methods=["DELETE"])
@require_auth
@require_permission("settings.system")
def delete_level(level_id):
    """Delete an access level. System roles cannot be deleted."""
    role = db.session.query(Role).filter_by(id=level_id).first()
    if not role:
        return jsonify({"error": "Access level not found"}), 404
    if role.is_system:
        return jsonify({"error": "System roles cannot be deleted"}), 400

    db.session.delete(role)
    db.session.commit()
    return jsonify({"message": "Access level deleted"}), 200


# ── Permissions ─────────────────────────────────────────────────────────


@access_bp.route("/permissions", methods=["GET"])
@require_auth
@require_permission("settings.system")
def list_permissions():
    """List all available permissions grouped by source (core + plugins)."""
    return jsonify({"permissions": _get_all_permissions()}), 200


# ── User Role Assignment ────────────────────────────────────────────────


@access_bp.route("/levels/<level_id>/users", methods=["GET"])
@require_auth
@require_permission("settings.system")
def list_level_users(level_id):
    """List users assigned to an access level."""
    role = db.session.query(Role).filter_by(id=level_id).first()
    if not role:
        return jsonify({"error": "Access level not found"}), 404

    users = [
        {"id": str(u.id), "email": u.email, "name": u.to_dict().get("name")}
        for u in role.users.all()
    ]
    return jsonify({"users": users}), 200


@access_bp.route("/users/<user_id>/roles", methods=["POST"])
@require_auth
@require_permission("settings.system")
def assign_user_role(user_id):
    """Assign a role to a user."""
    data = request.get_json() or {}
    role_id = data.get("role_id")
    if not role_id:
        return jsonify({"error": "role_id is required"}), 400

    user = db.session.query(User).filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    role = db.session.query(Role).filter_by(id=role_id).first()
    if not role:
        return jsonify({"error": "Role not found"}), 404

    # Check if already assigned
    existing = (
        db.session.query(user_roles).filter_by(user_id=user.id, role_id=role.id).first()
    )
    if existing:
        return jsonify({"message": "Role already assigned"}), 200

    db.session.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))
    db.session.commit()
    return jsonify({"message": "Role assigned"}), 200


@access_bp.route("/users/<user_id>/roles/<role_id>", methods=["DELETE"])
@require_auth
@require_permission("settings.system")
def revoke_user_role(user_id, role_id):
    """Revoke a role from a user."""
    db.session.query(user_roles).filter_by(user_id=user_id, role_id=role_id).delete()
    db.session.commit()
    return jsonify({"message": "Role revoked"}), 200


# ── Export / Import ─────────────────────────────────────────────────────


@access_bp.route("/export", methods=["POST"])
@require_auth
@require_permission("settings.system")
def export_access():
    """Export roles + permissions as JSON."""
    data = request.get_json() or {}
    role_ids = data.get("ids")

    query = db.session.query(Role)
    if role_ids:
        query = query.filter(Role.id.in_(role_ids))
    roles = query.all()

    export_data = {
        "version": 1,
        "roles": [
            {
                "slug": r.slug,
                "name": r.name,
                "description": r.description,
                "is_system": r.is_system,
                "permissions": [p.name for p in r.permissions],
            }
            for r in roles
        ],
    }

    return jsonify(export_data), 200


@access_bp.route("/import", methods=["POST"])
@require_auth
@require_permission("settings.system")
def import_access():
    """Import roles + permissions from JSON. Upserts by slug. System roles not overwritten."""
    data = request.get_json()
    if not data or "roles" not in data:
        return jsonify({"error": "Invalid format — expected {roles: [...]}"}), 400

    imported_count = 0
    for role_data in data["roles"]:
        slug = role_data.get("slug")
        if not slug:
            continue

        existing = db.session.query(Role).filter_by(slug=slug).first()
        if existing:
            if existing.is_system:
                continue  # Don't overwrite system roles
            existing.name = role_data.get("name", existing.name)
            existing.description = role_data.get("description", existing.description)
            _assign_permissions(existing, role_data.get("permissions", []))
        else:
            role = Role(
                id=uuid4(),
                name=role_data.get("name", slug),
                slug=slug,
                description=role_data.get("description", ""),
                is_system=False,
            )
            _assign_permissions(role, role_data.get("permissions", []))
            db.session.add(role)

        imported_count += 1

    db.session.commit()
    return jsonify({"imported": imported_count}), 200


# ── Helpers ─────────────────────────────────────────────────────────────


def _assign_permissions(role, permission_keys):
    """Assign permissions to a role by key names. Creates Permission records if needed."""
    role.permissions.clear()
    for key in permission_keys:
        perm = db.session.query(Permission).filter_by(name=key).first()
        if not perm:
            parts = key.rsplit(".", 1)
            perm = Permission(
                id=uuid4(),
                name=key,
                resource=parts[0] if len(parts) > 1 else key,
                action=parts[1] if len(parts) > 1 else "*",
                description=key,
            )
            db.session.add(perm)
            db.session.flush()
        role.permissions.append(perm)
