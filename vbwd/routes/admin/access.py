"""Admin access management routes — admin roles, access levels, assignments.

S94 Slice 6a (DC-1) flipped the inverted terminology:
  * ``/roles*``  manages **AdminRole** (System B, gates ``/admin``).
  * ``/levels*`` manages **AccessLevel** (System C, gates ``/user``) — this
    path FLIPPED meaning (it previously managed AdminRole).
  * The vacated ``/user-levels*`` paths 308-redirect to ``/levels*`` for one
    release so cached clients degrade gracefully.
"""
from uuid import uuid4

from flask import Blueprint, g, jsonify, redirect, request
from vbwd.extensions import db
from vbwd.middleware.auth import require_auth, require_permission
from vbwd.models.enums import UserRole
from vbwd.models.role import Role, Permission, user_roles
from vbwd.models.user import User
from vbwd.models.user_access_level import (
    AccessLevel,
    user_user_access_levels,
)

access_bp = Blueprint("admin_access", __name__, url_prefix="/api/v1/admin/access")


def _acting_user_is_super_admin() -> bool:
    """True when the authenticated caller is a SUPER_ADMIN.

    System roles / user access levels are protected from deletion for ordinary
    admins, but a super admin may remove them (e.g. the default ``admin`` role).
    """
    user = getattr(g, "user", None)
    return user is not None and user.role == UserRole.SUPER_ADMIN


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
    {
        "key": "api_keys.manage",
        "label": "Manage user API keys",
        "group": "API Keys",
    },
    {
        "key": "llm.connections.view",
        "label": "View LLM connections",
        "group": "LLM Connections",
    },
    {
        "key": "llm.connections.manage",
        "label": "Manage LLM connections",
        "group": "LLM Connections",
    },
    {
        "key": "logs.read",
        "label": "Read system logs",
        "group": "Observability",
    },
]

# User-facing permission for self-service API-key management. Seeded into the
# permission catalogue so an admin can grant it to user access levels; gates
# the fe-user nav item, page route, and the self-service backend routes
# (defence-in-depth, never FE-only).
CORE_USER_PERMISSIONS = [
    {"key": "manage_api", "label": "Manage own API keys", "group": "API"},
]


def _get_all_permissions():
    """Collect permissions from core + all enabled plugins.

    Thin wrapper over the shared catalog collector (DRY) — the seeder uses
    the same source.
    """
    from vbwd.services.permission_catalog import collect_permission_catalog

    return collect_permission_catalog()


# ── Admin Roles (System B — gate /admin) ────────────────────────────────


@access_bp.route("/roles", methods=["GET"])
@require_auth
@require_permission("settings.system")
def list_levels():
    """List all admin roles with permissions."""
    roles = db.session.query(Role).order_by(Role.is_system.desc(), Role.name).all()
    return jsonify({"levels": [r.to_dict() for r in roles]}), 200


@access_bp.route("/roles", methods=["POST"])
@require_auth
@require_permission("settings.system")
def create_level():
    """Create a new admin role."""
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


@access_bp.route("/roles/<level_id>", methods=["GET"])
@require_auth
@require_permission("settings.system")
def get_level(level_id):
    """Get admin role detail with assigned users."""
    role = db.session.query(Role).filter_by(id=level_id).first()
    if not role:
        return jsonify({"error": "Access level not found"}), 404

    result = role.to_dict()
    result["users"] = [
        {"id": str(u.id), "email": u.email, "name": u.to_dict().get("name")}
        for u in role.users.all()
    ]
    return jsonify({"level": result}), 200


@access_bp.route("/roles/<level_id>", methods=["PUT"])
@require_auth
@require_permission("settings.system")
def update_level(level_id):
    """Update an admin role and its permissions."""
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


@access_bp.route("/roles/<level_id>", methods=["DELETE"])
@require_auth
@require_permission("settings.system")
def delete_level(level_id):
    """Delete an admin role. System roles are deletable only by a super admin."""
    role = db.session.query(Role).filter_by(id=level_id).first()
    if not role:
        return jsonify({"error": "Access level not found"}), 404
    if role.is_system and not _acting_user_is_super_admin():
        return (
            jsonify({"error": "System roles can only be deleted by a super admin"}),
            400,
        )

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


@access_bp.route("/roles/<level_id>/users", methods=["GET"])
@require_auth
@require_permission("settings.system")
def list_level_users(level_id):
    """List users assigned to an admin role."""
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


# ── Access Levels (System C — gate /user) ───────────────────────────────


def _get_all_user_permissions():
    """Collect user permissions from core + all enabled plugins.

    Thin wrapper over the shared catalog collector (DRY) — the RBAC seeder
    uses the same source, so seeded access-level grants and the admin UI's
    permission picker never drift.
    """
    from vbwd.services.permission_catalog import collect_user_permission_catalog

    return collect_user_permission_catalog()


@access_bp.route("/levels", methods=["GET"])
@require_auth
@require_permission("settings.system")
def list_user_levels():
    """List all access levels (System C)."""
    levels = (
        db.session.query(AccessLevel)
        .order_by(AccessLevel.is_system.desc(), AccessLevel.name)
        .all()
    )
    return jsonify({"levels": [level.to_dict() for level in levels]}), 200


@access_bp.route("/levels", methods=["POST"])
@require_auth
@require_permission("settings.system")
def create_user_level():
    """Create a new access level (System C)."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    slug = data.get("slug") or name.lower().replace(" ", "-")
    if db.session.query(AccessLevel).filter_by(slug=slug).first():
        return jsonify({"error": f"Access level '{slug}' already exists"}), 400

    level = AccessLevel(
        id=uuid4(),
        name=name,
        slug=slug,
        description=data.get("description", ""),
        is_system=False,
        linked_plan_slug=data.get("linked_plan_slug") or None,
    )

    permission_keys = data.get("permissions", [])
    _assign_permissions(level, permission_keys)

    db.session.add(level)
    db.session.commit()
    return jsonify({"level": level.to_dict()}), 201


@access_bp.route("/levels/<level_id>", methods=["GET"])
@require_auth
@require_permission("settings.system")
def get_user_level(level_id):
    """Get access level detail (System C) with assigned users."""
    level = db.session.query(AccessLevel).filter_by(id=level_id).first()
    if not level:
        return jsonify({"error": "Access level not found"}), 404

    result = level.to_dict()
    result["users"] = [
        {"id": str(u.id), "email": u.email, "name": u.to_dict().get("name")}
        for u in level.users.all()
    ]
    return jsonify({"level": result}), 200


@access_bp.route("/levels/<level_id>", methods=["PUT"])
@require_auth
@require_permission("settings.system")
def update_user_level(level_id):
    """Update an access level (System C) and its permissions."""
    level = db.session.query(AccessLevel).filter_by(id=level_id).first()
    if not level:
        return jsonify({"error": "Access level not found"}), 404

    data = request.get_json() or {}

    if "name" in data:
        level.name = data["name"]
    if "slug" in data and data["slug"] != level.slug:
        existing = db.session.query(AccessLevel).filter_by(slug=data["slug"]).first()
        if existing:
            return jsonify({"error": f"Slug '{data['slug']}' already exists"}), 400
        level.slug = data["slug"]
    if "description" in data:
        level.description = data["description"]
    if "linked_plan_slug" in data:
        level.linked_plan_slug = data["linked_plan_slug"] or None
    if "permissions" in data:
        _assign_permissions(level, data["permissions"])

    db.session.commit()
    return jsonify({"level": level.to_dict()}), 200


@access_bp.route("/levels/<level_id>", methods=["DELETE"])
@require_auth
@require_permission("settings.system")
def delete_user_level(level_id):
    """Delete an access level. System levels are deletable only by a super admin."""
    level = db.session.query(AccessLevel).filter_by(id=level_id).first()
    if not level:
        return jsonify({"error": "Access level not found"}), 404
    if level.is_system and not _acting_user_is_super_admin():
        return (
            jsonify({"error": "System levels can only be deleted by a super admin"}),
            400,
        )

    db.session.delete(level)
    db.session.commit()
    return jsonify({"message": "Access level deleted"}), 200


@access_bp.route("/user-permissions", methods=["GET"])
@require_auth
@require_permission("settings.system")
def list_user_permissions():
    """List all available user permissions grouped by plugin."""
    return jsonify({"permissions": _get_all_user_permissions()}), 200


@access_bp.route("/levels/<level_id>/content", methods=["GET"])
@require_auth
@require_permission("settings.system")
def get_user_level_content(level_id):
    """List content (across all plugins) restricted to a specific access level.

    Iterates every registered ``IAccessLevelContentProvider`` (S01) and
    merges their categorised results. Empty mapping when no content-owning
    plugin is enabled — Liskov-safe null default at the registry.
    """
    level = db.session.query(AccessLevel).filter_by(id=level_id).first()
    if not level:
        return jsonify({"error": "Access level not found"}), 404

    from vbwd.services.access_level_content_provider import (
        resolve_access_level_content_providers,
    )

    merged: dict[str, list] = {}
    for provider in resolve_access_level_content_providers():
        for category, items in provider.list_restricted_content_for_level(
            level_id
        ).items():
            merged.setdefault(category, []).extend(items)

    # Always return the legacy CMS-shaped keys so FE consumers that read
    # ``response.pages`` / ``response.widgets`` keep working when no
    # content-owning plugin is enabled.
    merged.setdefault("pages", [])
    merged.setdefault("widgets", [])
    return jsonify(merged), 200


@access_bp.route("/users/<user_id>/user-access-levels", methods=["POST"])
@require_auth
@require_permission("settings.system")
def assign_user_access_level(user_id):
    """Assign a user access level to a user."""
    data = request.get_json() or {}
    level_id = data.get("level_id")
    if not level_id:
        return jsonify({"error": "level_id is required"}), 400

    user = db.session.query(User).filter_by(id=user_id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    level = db.session.query(AccessLevel).filter_by(id=level_id).first()
    if not level:
        return jsonify({"error": "Access level not found"}), 404

    existing = (
        db.session.query(user_user_access_levels)
        .filter_by(user_id=user.id, user_access_level_id=level.id)
        .first()
    )
    if existing:
        return jsonify({"message": "Level already assigned"}), 200

    db.session.execute(
        user_user_access_levels.insert().values(
            user_id=user.id, user_access_level_id=level.id
        )
    )
    db.session.commit()
    return jsonify({"message": "User access level assigned"}), 200


@access_bp.route("/users/<user_id>/user-access-levels/<level_id>", methods=["DELETE"])
@require_auth
@require_permission("settings.system")
def revoke_user_access_level(user_id, level_id):
    """Revoke a user access level from a user."""
    db.session.query(user_user_access_levels).filter_by(
        user_id=user_id, user_access_level_id=level_id
    ).delete()
    db.session.commit()
    return jsonify({"message": "User access level revoked"}), 200


# ── 308 redirects: vacated /user-levels* → /levels* (one release) ────────
#
# System C moved from ``/user-levels*`` to ``/levels*``. The old paths are now
# vacant (System B took ``/roles*``, not ``/levels*``), so we can safely 308
# them to the new home — preserving method, sub-path, and query string so a
# cached client's POST/PUT/DELETE still lands correctly. Auth-marked so the
# route-exposure oracle stays green.

PERMANENT_REDIRECT_STATUS = 308


def _redirect_to(new_path: str):
    """308-redirect to ``new_path`` on the access blueprint, keeping the query."""
    target = f"/api/v1/admin/access{new_path}"
    if request.query_string:
        target = f"{target}?{request.query_string.decode()}"
    return redirect(target, code=PERMANENT_REDIRECT_STATUS)


@access_bp.route("/user-levels", methods=["GET", "POST"])
@require_auth
@require_permission("settings.system")
def redirect_user_levels_collection():
    """Legacy ``/user-levels`` → ``/levels`` (System C moved)."""
    return _redirect_to("/levels")


@access_bp.route("/user-levels/<level_id>", methods=["GET", "PUT", "DELETE"])
@require_auth
@require_permission("settings.system")
def redirect_user_level_item(level_id):
    """Legacy ``/user-levels/<id>`` → ``/levels/<id>`` (System C moved)."""
    return _redirect_to(f"/levels/{level_id}")


@access_bp.route("/user-levels/<level_id>/content", methods=["GET"])
@require_auth
@require_permission("settings.system")
def redirect_user_level_content(level_id):
    """Legacy ``/user-levels/<id>/content`` → ``/levels/<id>/content``."""
    return _redirect_to(f"/levels/{level_id}/content")


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
