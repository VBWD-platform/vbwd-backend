"""Admin LLM-connection routes (S97.2).

CRUD + bulk(delete/activate) + make-default over the admin-managed
``LlmConnection`` registry, mirroring the ``currency.py`` shape. Every read
returns a MASKED api_key (first 16 chars then an ellipsis) — the full key is
never echoed. Reads require ``llm.connections.view``; writes require
``llm.connections.manage``.
"""
from flask import Blueprint, jsonify, request

from vbwd.extensions import db
from vbwd.middleware.auth import require_auth, require_permission
from vbwd.repositories.llm_connection_repository import LlmConnectionRepository
from vbwd.services.llm_connection_service import (
    LlmConnectionService,
    NoActiveLlmConnectionError,
)

admin_llm_connections_bp = Blueprint(
    "admin_llm_connections", __name__, url_prefix="/api/v1/admin/llm-connections"
)

PERM_VIEW = "llm.connections.view"
PERM_MANAGE = "llm.connections.manage"

# The connection fields an admin may set on create/update (never ``is_default``,
# which flows only through make-default; never an echoed/derived field).
_WRITABLE_FIELDS = (
    "slug",
    "connection_name",
    "api_endpoint",
    "api_key",
    "model",
    "provider",
    "temperature",
    "max_tokens",
    "timeout",
    "is_active",
)

_DEFAULT_PAGE_SIZE = 25
_SORTABLE_FIELDS = {"connection_name", "slug", "model", "last_active_at", "is_default"}


def _build_service() -> LlmConnectionService:
    """Build a request-scoped service over the live session."""
    return LlmConnectionService(repository=LlmConnectionRepository(db.session))


def _writable_payload(data: dict) -> dict:
    """Return only the writable fields present in ``data``."""
    return {key: data[key] for key in _WRITABLE_FIELDS if key in data}


def _matches_query(row_dict: dict, query: str) -> bool:
    haystack = " ".join(
        str(row_dict.get(field) or "")
        for field in ("connection_name", "slug", "model", "api_endpoint")
    ).lower()
    return query in haystack


@admin_llm_connections_bp.route("", methods=["GET"])
@require_auth
@require_permission(PERM_VIEW)
def list_connections():
    """List connections (masked keys only), with search/sort/paginate."""
    service = _build_service()
    rows = [connection.to_dict() for connection in service.list_all()]

    query = (request.args.get("q") or "").strip().lower()
    if query:
        rows = [row for row in rows if _matches_query(row, query)]

    sort_by = request.args.get("sort_by", "connection_name")
    if sort_by not in _SORTABLE_FIELDS:
        sort_by = "connection_name"
    descending = request.args.get("order", "asc").lower() == "desc"
    rows.sort(
        key=lambda row: (row.get(sort_by) is None, row.get(sort_by) or ""),
        reverse=descending,
    )

    total = len(rows)
    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = max(1, int(request.args.get("page_size", _DEFAULT_PAGE_SIZE)))
    except (TypeError, ValueError):
        page, page_size = 1, _DEFAULT_PAGE_SIZE
    start = (page - 1) * page_size
    paged = rows[start : start + page_size]

    return (
        jsonify(
            {"connections": paged, "total": total, "page": page, "page_size": page_size}
        ),
        200,
    )


@admin_llm_connections_bp.route("", methods=["POST"])
@require_auth
@require_permission(PERM_MANAGE)
def create_connection():
    """Create a connection (never default; activate/make-default separately)."""
    data = request.get_json() or {}
    payload = _writable_payload(data)
    required = ("slug", "connection_name", "model", "api_key")
    missing = [field for field in required if not payload.get(field)]
    if missing:
        return jsonify({"error": f"missing required: {', '.join(missing)}"}), 400

    service = _build_service()
    try:
        connection = service.create(**payload)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"connection": connection.to_dict()}), 201


@admin_llm_connections_bp.route("/test", methods=["POST"])
@require_auth
@require_permission(PERM_MANAGE)
def test_connection():
    """Validate an endpoint/model/key triple with one live call — before saving.

    Returns ``200 {ok:true, sample}`` when the provider answers, or
    ``200 {ok:false, error}`` when it doesn't (a bad key/model/endpoint is a
    *result*, not a server error). When the key is blank but a ``slug`` names an
    existing connection, its stored key (and endpoint, if omitted) are reused —
    matching the form's "leave blank to keep current". The key is never echoed.
    """
    from vbwd.llm.errors import LlmError

    data = request.get_json(silent=True) or {}
    model = (data.get("model") or "").strip()
    api_endpoint = (data.get("api_endpoint") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    slug = (data.get("slug") or "").strip()
    if not model:
        return jsonify({"ok": False, "error": "model is required"}), 400

    service = _build_service()
    if not api_key and slug:
        existing = service.get_by_slug(slug)
        if existing is not None:
            api_key = existing.api_key
            if not api_endpoint:
                api_endpoint = existing.api_endpoint or ""
    if not api_key:
        return jsonify({"ok": False, "error": "api_key is required"}), 400

    try:
        sample = service.test_connection(
            model=model, api_endpoint=api_endpoint, api_key=api_key
        )
        return jsonify(
            {
                "ok": True,
                "message": "Connection succeeded",
                "sample": (sample or "")[:200],
            }
        )
    except LlmError as error:
        return jsonify({"ok": False, "error": str(error)}), 200
    except Exception as error:  # pragma: no cover - unexpected transport oddity
        return jsonify({"ok": False, "error": f"{type(error).__name__}: {error}"}), 200


@admin_llm_connections_bp.route("/<connection_id>", methods=["PUT"])
@require_auth
@require_permission(PERM_MANAGE)
def update_connection(connection_id):
    """Update a connection's writable fields."""
    data = request.get_json() or {}
    service = _build_service()
    try:
        connection = service.update(connection_id, **_writable_payload(data))
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"connection": connection.to_dict()}), 200


@admin_llm_connections_bp.route("/<connection_id>", methods=["DELETE"])
@require_auth
@require_permission(PERM_MANAGE)
def delete_connection(connection_id):
    """Delete a connection (deleting the default just clears the default)."""
    service = _build_service()
    service.delete(connection_id)
    return jsonify({"status": "deleted"}), 200


@admin_llm_connections_bp.route("/bulk-delete", methods=["POST"])
@require_auth
@require_permission(PERM_MANAGE)
def bulk_delete_connections():
    """Delete several connections by id."""
    data = request.get_json() or {}
    ids = data.get("ids") or []
    service = _build_service()
    deleted = service.bulk_delete(ids)
    return jsonify({"deleted": deleted}), 200


@admin_llm_connections_bp.route("/bulk-activate", methods=["POST"])
@require_auth
@require_permission(PERM_MANAGE)
def bulk_activate_connections():
    """Activate or deactivate several connections (``active`` boolean)."""
    data = request.get_json() or {}
    ids = data.get("ids") or []
    active = bool(data.get("active", True))
    service = _build_service()
    connections = service.set_active(ids, active)
    return (
        jsonify({"connections": [c.to_dict() for c in connections]}),
        200,
    )


@admin_llm_connections_bp.route("/<connection_id>/make-default", methods=["POST"])
@require_auth
@require_permission(PERM_MANAGE)
def make_default(connection_id):
    """Make a connection the single, active default (idempotent)."""
    service = _build_service()
    try:
        connection = service.set_default(connection_id)
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"connection": connection.to_dict()}), 200


@admin_llm_connections_bp.route("/resolve", methods=["GET"])
@require_auth
@require_permission(PERM_VIEW)
def resolve_connection():
    """Resolve the connection a slug would select (proves by-slug vs default).

    ``?slug=<slug>`` resolves that specific (active) connection; no slug
    resolves the active default. Echoes the resolved connection (masked) — used
    by the walkthrough/tests to assert a configured slug resolves to that
    connection, not the default. Raises 404 when none is resolvable.
    """
    slug = request.args.get("slug")
    service = _build_service()
    try:
        service.llm_client(slug=slug or None)
    except NoActiveLlmConnectionError as error:
        return jsonify({"error": str(error)}), 404
    connection = service.get_by_slug(slug) if slug else service.get_default()
    if connection is None:
        return jsonify({"error": "connection not found"}), 404
    return jsonify({"connection": connection.to_dict()}), 200
