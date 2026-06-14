"""Admin tags + custom-fields routes (S77 slice 2).

Three concerns, one blueprint:

* **Tag catalog** CRUD + bulk-delete (gated ``settings.manage``); the list
  carries a usage ``stats`` count per row, computed in ONE grouped query.
* **Custom-field-def** CRUD + bulk-delete (gated ``settings.manage``), plus the
  registered entity-type listing that drives the admin parent-entity filter.
* **Generic per-entity value endpoints** ``GET|PUT /<entity_type>/<id>/{tags,
  custom-fields}``: the entity type is looked up in the registry (unregistered
  → 404) and the value write is gated by *that* registration's own
  ``manage_permission`` — the consumer owns its gating, core hard-codes none.

The value endpoints resolve the :class:`ITagsAndCustomFields` port from the DI
container; the catalog CRUD uses ``TagService`` / ``CustomFieldService`` over
the live ``db.session``. No plugin imports — fully core-agnostic.
"""
from typing import cast

from flask import Blueprint, g, jsonify, request
from sqlalchemy.orm import Session

from vbwd.extensions import db
from vbwd.middleware.auth import require_auth, require_permission
from vbwd.repositories.custom_field_def_repository import CustomFieldDefRepository
from vbwd.repositories.custom_field_value_repository import (
    CustomFieldValueRepository,
)
from vbwd.repositories.entity_tag_repository import EntityTagRepository
from vbwd.repositories.tag_repository import TagRepository
from vbwd.services.custom_field_service import CustomFieldService
from vbwd.services.entity_type_registry import get_entity_type, list_entity_types
from vbwd.services.tag_service import TagService
from vbwd.services.tags_and_custom_fields import (
    CustomFieldValidationError,
    UnknownCustomFieldError,
    UnknownEntityTypeError,
)

admin_tags_custom_fields_bp = Blueprint(
    "admin_tags_custom_fields", __name__, url_prefix="/api/v1/admin"
)


def _session() -> Session:
    """The live request-scoped SQLAlchemy session (typed for the repos)."""
    return cast(Session, db.session)


def _tag_service() -> TagService:
    return TagService(
        tag_repo=TagRepository(_session()),
        entity_tag_repo=EntityTagRepository(_session()),
    )


def _custom_field_service() -> CustomFieldService:
    return CustomFieldService(
        def_repo=CustomFieldDefRepository(_session()),
        value_repo=CustomFieldValueRepository(_session()),
    )


# ── tag catalog CRUD + bulk-delete ───────────────────────────────────────────


@admin_tags_custom_fields_bp.route("/tags", methods=["GET"])
@require_auth
@require_permission("settings.manage")
def list_tags():
    """List the tag catalog; each row carries a usage ``stats`` count."""
    parent_entity_type = request.args.get("parent_entity_type")
    tags = _tag_service().list_tags_with_stats(parent_entity_type=parent_entity_type)
    return jsonify({"tags": tags}), 200


@admin_tags_custom_fields_bp.route("/tags", methods=["POST"])
@require_auth
@require_permission("settings.manage")
def create_tag():
    """Create a catalog tag."""
    data = request.get_json() or {}
    slug = data.get("slug")
    name = data.get("name")
    if not slug or not name:
        return jsonify({"error": "slug and name are required"}), 400
    tag = _tag_service().create_tag(
        slug=slug,
        name=name,
        parent_entity_type=data.get("parent_entity_type"),
        meta_data=data.get("meta_data"),
        color=data.get("color"),
    )
    return jsonify({"tag": tag.to_dict()}), 201


@admin_tags_custom_fields_bp.route("/tags/<slug>", methods=["PUT"])
@require_auth
@require_permission("settings.manage")
def update_tag(slug):
    """Update a catalog tag's mutable fields."""
    data = request.get_json() or {}
    changes = {
        field: data[field]
        for field in ("name", "parent_entity_type", "meta_data", "color")
        if field in data
    }
    tag = _tag_service().update_tag(slug, **changes)
    if tag is None:
        return jsonify({"error": f"Tag not found: {slug}"}), 404
    return jsonify({"tag": tag.to_dict()}), 200


@admin_tags_custom_fields_bp.route("/tags/<slug>", methods=["DELETE"])
@require_auth
@require_permission("settings.manage")
def delete_tag(slug):
    """Delete a catalog tag (cascades its ``entity_tag`` rows via the FK)."""
    if not _tag_service().delete_tag(slug):
        return jsonify({"error": f"Tag not found: {slug}"}), 404
    return jsonify({"deleted": 1}), 200


@admin_tags_custom_fields_bp.route("/tags/bulk-delete", methods=["POST"])
@require_auth
@require_permission("settings.manage")
def bulk_delete_tags():
    """Delete several catalog tags by slug."""
    data = request.get_json() or {}
    slugs = data.get("slugs")
    if not isinstance(slugs, list):
        return jsonify({"error": "slugs must be a list"}), 400
    service = _tag_service()
    deleted = sum(1 for slug in slugs if service.delete_tag(slug))
    return jsonify({"deleted": deleted}), 200


# ── custom-field-def CRUD + bulk-delete ──────────────────────────────────────


@admin_tags_custom_fields_bp.route("/custom-fields", methods=["GET"])
@require_auth
@require_permission("settings.manage")
def list_custom_fields():
    """List the def catalog, optionally filtered by entity_type and/or type."""
    defs = _custom_field_service().list_defs(
        entity_type=request.args.get("entity_type"),
        field_type=request.args.get("type"),
    )
    return jsonify({"custom_fields": defs}), 200


@admin_tags_custom_fields_bp.route("/custom-fields", methods=["POST"])
@require_auth
@require_permission("settings.manage")
def create_custom_field():
    """Create a custom-field definition."""
    data = request.get_json() or {}
    entity_type = data.get("entity_type")
    key = data.get("key")
    label = data.get("label")
    field_type = data.get("type")
    if not entity_type or not key or not label or not field_type:
        return jsonify({"error": "entity_type, key, label and type are required"}), 400
    try:
        definition = _custom_field_service().create_def(
            entity_type=entity_type,
            key=key,
            label=label,
            field_type=field_type,
            options=data.get("options"),
            sort_order=data.get("sort_order", 0),
            is_active=data.get("is_active", True),
        )
    except CustomFieldValidationError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"custom_field": definition.to_dict()}), 201


@admin_tags_custom_fields_bp.route("/custom-fields/<def_id>", methods=["PUT"])
@require_auth
@require_permission("settings.manage")
def update_custom_field(def_id):
    """Update a def's mutable fields by primary id."""
    data = request.get_json() or {}
    changes = {
        field: data[field]
        for field in ("label", "type", "options", "sort_order", "is_active")
        if field in data
    }
    definition = _custom_field_service().update_def_by_id(def_id, **changes)
    if definition is None:
        return jsonify({"error": f"Custom field not found: {def_id}"}), 404
    return jsonify({"custom_field": definition.to_dict()}), 200


@admin_tags_custom_fields_bp.route("/custom-fields/<def_id>", methods=["DELETE"])
@require_auth
@require_permission("settings.manage")
def delete_custom_field(def_id):
    """Delete a def by primary id."""
    if not _custom_field_service().delete_def_by_id(def_id):
        return jsonify({"error": f"Custom field not found: {def_id}"}), 404
    return jsonify({"deleted": 1}), 200


@admin_tags_custom_fields_bp.route("/custom-fields/bulk-delete", methods=["POST"])
@require_auth
@require_permission("settings.manage")
def bulk_delete_custom_fields():
    """Delete several defs by primary id."""
    data = request.get_json() or {}
    ids = data.get("ids")
    if not isinstance(ids, list):
        return jsonify({"error": "ids must be a list"}), 400
    service = _custom_field_service()
    deleted = sum(1 for def_id in ids if service.delete_def_by_id(def_id))
    return jsonify({"deleted": deleted}), 200


# ── registered entity-type listing (drives the admin parent-entity filter) ───


@admin_tags_custom_fields_bp.route("/custom-field-entity-types", methods=["GET"])
@require_auth
@require_permission("settings.manage")
def list_custom_field_entity_types():
    """List the registered entity types (entity_type, label, manage_permission)."""
    entity_types = [
        {
            "entity_type": registration.entity_type,
            "label": registration.label,
            "manage_permission": registration.manage_permission,
        }
        for registration in list_entity_types()
    ]
    return jsonify({"entity_types": entity_types}), 200


# ── generic per-entity value endpoints (gated by the entity's own perm) ──────


def _require_entity_manage(entity_type: str):
    """Resolve the entity type and enforce its manage_permission.

    Returns an error ``(response, status)`` to return early, or ``None`` to
    proceed. Unregistered type → 404 (the consumer owns the type); missing the
    registration's ``manage_permission`` → 403 (the consumer owns its gating).
    """
    registration = get_entity_type(entity_type)
    if registration is None:
        return jsonify({"error": f"Unknown entity type: {entity_type}"}), 404
    if not g.user.has_permission(registration.manage_permission):
        return (
            jsonify(
                {
                    "error": "Permission denied",
                    "required": registration.manage_permission,
                }
            ),
            403,
        )
    return None


def _port():
    from flask import current_app

    return current_app.container.tags_and_custom_fields()  # type: ignore[attr-defined]


@admin_tags_custom_fields_bp.route("/<entity_type>/<entity_id>/tags", methods=["GET"])
@require_auth
def get_entity_tags(entity_type, entity_id):
    """Tag slugs attached to one entity."""
    guard = _require_entity_manage(entity_type)
    if guard is not None:
        return guard
    return jsonify({"tags": _port().get_tags(entity_type, entity_id)}), 200


@admin_tags_custom_fields_bp.route("/<entity_type>/<entity_id>/tags", methods=["PUT"])
@require_auth
def set_entity_tags(entity_type, entity_id):
    """Replace the full tag set for one entity (full-replace)."""
    guard = _require_entity_manage(entity_type)
    if guard is not None:
        return guard
    data = request.get_json() or {}
    slugs = data.get("tags")
    if not isinstance(slugs, list):
        return jsonify({"error": "tags must be a list"}), 400
    _port().set_tags(entity_type, entity_id, slugs)
    return jsonify({"tags": _port().get_tags(entity_type, entity_id)}), 200


@admin_tags_custom_fields_bp.route(
    "/<entity_type>/<entity_id>/custom-fields", methods=["GET"]
)
@require_auth
def get_entity_custom_fields(entity_type, entity_id):
    """Custom-field values for one entity."""
    guard = _require_entity_manage(entity_type)
    if guard is not None:
        return guard
    values = _port().get_custom_fields(entity_type, entity_id)
    return jsonify({"custom_fields": values}), 200


@admin_tags_custom_fields_bp.route(
    "/<entity_type>/<entity_id>/custom-fields", methods=["PUT"]
)
@require_auth
def set_entity_custom_fields(entity_type, entity_id):
    """Partial upsert of custom-field values for one entity (``None`` clears)."""
    guard = _require_entity_manage(entity_type)
    if guard is not None:
        return guard
    data = request.get_json() or {}
    values = data.get("custom_fields")
    if not isinstance(values, dict):
        return jsonify({"error": "custom_fields must be an object"}), 400
    try:
        _port().set_custom_fields(entity_type, entity_id, values)
    except (
        CustomFieldValidationError,
        UnknownCustomFieldError,
        UnknownEntityTypeError,
    ) as error:
        return jsonify({"error": str(error)}), 400
    updated = _port().get_custom_fields(entity_type, entity_id)
    return jsonify({"custom_fields": updated}), 200
