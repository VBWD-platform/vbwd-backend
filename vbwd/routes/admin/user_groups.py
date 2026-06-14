"""Admin user-group routes (S73).

Two surfaces, both absolute-pathed under one blueprint:

* ``/api/v1/admin/user-groups`` — CRUD + bulk-delete (gated ``settings.manage``);
* ``/api/v1/admin/users/<id>/groups`` — read / replace-set a user's group
  membership by slug (gated ``users.manage``).

Routes are thin: validation + persistence live in ``UserGroupService`` and the
``IUserGroupMembership`` port (core stays plugin-agnostic).
"""
from uuid import UUID

from flask import Blueprint, jsonify, request

from vbwd.extensions import db
from vbwd.middleware.auth import require_auth, require_permission
from vbwd.services.user_group_membership import resolve_user_group_membership
from vbwd.services.user_group_service import (
    UserGroupService,
    UserGroupValidationError,
)

admin_user_groups_bp = Blueprint("admin_user_groups", __name__)


def _service() -> UserGroupService:
    return UserGroupService(db.session)


# ── User Groups CRUD ─────────────────────────────────────────────────────────


@admin_user_groups_bp.route("/api/v1/admin/user-groups", methods=["GET"])
@require_auth
@require_permission("settings.manage")
def list_user_groups():
    groups = _service().list_groups()
    return jsonify({"groups": [group.to_dict() for group in groups]}), 200


@admin_user_groups_bp.route("/api/v1/admin/user-groups", methods=["POST"])
@require_auth
@require_permission("settings.manage")
def create_user_group():
    data = request.get_json() or {}
    try:
        group = _service().create_group(
            slug=data.get("slug", ""),
            name=data.get("name", ""),
            lang=data.get("lang"),
            parent_group=data.get("parent_group"),
        )
    except UserGroupValidationError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"group": group.to_dict()}), 201


@admin_user_groups_bp.route("/api/v1/admin/user-groups/bulk-delete", methods=["POST"])
@require_auth
@require_permission("settings.manage")
def bulk_delete_user_groups():
    data = request.get_json() or {}
    group_ids = data.get("ids") or []
    if not isinstance(group_ids, list):
        return jsonify({"error": "ids must be a list"}), 400
    deleted = _service().bulk_delete([str(group_id) for group_id in group_ids])
    return jsonify({"deleted": deleted}), 200


@admin_user_groups_bp.route("/api/v1/admin/user-groups/<group_id>", methods=["GET"])
@require_auth
@require_permission("settings.manage")
def get_user_group(group_id):
    group = _service().get_by_id(group_id)
    if group is None:
        return jsonify({"error": "User group not found"}), 404
    return jsonify({"group": group.to_dict()}), 200


@admin_user_groups_bp.route("/api/v1/admin/user-groups/<group_id>", methods=["PUT"])
@require_auth
@require_permission("settings.manage")
def update_user_group(group_id):
    data = request.get_json() or {}
    try:
        group = _service().update_group(group_id, data)
    except UserGroupValidationError as error:
        return jsonify({"error": str(error)}), 400
    if group is None:
        return jsonify({"error": "User group not found"}), 404
    return jsonify({"group": group.to_dict()}), 200


@admin_user_groups_bp.route("/api/v1/admin/user-groups/<group_id>", methods=["DELETE"])
@require_auth
@require_permission("settings.manage")
def delete_user_group(group_id):
    if not _service().delete_group(group_id):
        return jsonify({"error": "User group not found"}), 404
    return jsonify({"message": "User group deleted"}), 200


# ── User membership (replace-set of slugs) ───────────────────────────────────


@admin_user_groups_bp.route("/api/v1/admin/users/<user_id>/groups", methods=["GET"])
@require_auth
@require_permission("users.manage")
def get_user_groups(user_id):
    membership = resolve_user_group_membership()
    slugs = sorted(membership.list_user_group_slugs(UUID(str(user_id))))
    return jsonify({"group_slugs": slugs}), 200


@admin_user_groups_bp.route("/api/v1/admin/users/<user_id>/groups", methods=["PUT"])
@require_auth
@require_permission("users.manage")
def set_user_groups(user_id):
    data = request.get_json() or {}
    slugs = data.get("group_slugs")
    if not isinstance(slugs, list):
        return jsonify({"error": "group_slugs must be a list"}), 400
    membership = resolve_user_group_membership()
    membership.set_user_groups(UUID(str(user_id)), [str(slug) for slug in slugs])
    db.session.commit()
    result = sorted(membership.list_user_group_slugs(UUID(str(user_id))))
    return jsonify({"group_slugs": result}), 200
