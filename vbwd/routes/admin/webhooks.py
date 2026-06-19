"""Admin outbound-webhook routes (core, plugin-agnostic).

CRUD + toggle + test over admin-registered outbound webhook endpoints, plus
a subscribable event-type catalog. JSON shapes match the fe-admin
``stores/webhooks.ts`` contract exactly:

    list:   {webhooks, total, page, per_page}
    get:    {webhook: {..., delivery_history: [...]}}
    write:  {webhook: {...}}

All endpoints require admin auth + ``settings.manage`` — the same permission
the fe webhooks settings surface guards on.
"""
from flask import Blueprint, jsonify, request

from vbwd.extensions import db
from vbwd.middleware.auth import require_auth, require_permission
from vbwd.repositories.webhook_delivery_repository import WebhookDeliveryRepository
from vbwd.repositories.webhook_subscription_repository import (
    WebhookSubscriptionRepository,
)
from vbwd.webhooks.event_types import list_webhook_event_types
from vbwd.webhooks.outbound_service import OutboundWebhookService

admin_webhooks_bp = Blueprint(
    "admin_webhooks", __name__, url_prefix="/api/v1/admin/webhooks"
)

PERM_MANAGE = "settings.manage"

_DEFAULT_PER_PAGE = 20
_DELIVERY_HISTORY_LIMIT = 50


def _build_service() -> OutboundWebhookService:
    """Build a request-scoped service over the live session."""
    return OutboundWebhookService(
        subscription_repository=WebhookSubscriptionRepository(db.session),
        delivery_repository=WebhookDeliveryRepository(db.session),
    )


@admin_webhooks_bp.route("", methods=["GET"])
@require_auth
@require_permission(PERM_MANAGE)
def list_webhooks():
    """List endpoints, paginated, optionally filtered by status."""
    service = _build_service()
    rows = [endpoint.to_dict() for endpoint in service.list_all()]

    status_filter = (request.args.get("status") or "").strip().lower()
    if status_filter:
        rows = [row for row in rows if row["status"] == status_filter]

    total = len(rows)
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(1, int(request.args.get("per_page", _DEFAULT_PER_PAGE)))
    except (TypeError, ValueError):
        page, per_page = 1, _DEFAULT_PER_PAGE
    start = (page - 1) * per_page
    paged = rows[start : start + per_page]

    return (
        jsonify(
            {"webhooks": paged, "total": total, "page": page, "per_page": per_page}
        ),
        200,
    )


@admin_webhooks_bp.route("/event-types", methods=["GET"])
@require_auth
@require_permission(PERM_MANAGE)
def list_event_types():
    """Return the subscribable event-type catalog as ``[{value, label}]``."""
    return jsonify({"event_types": list_webhook_event_types()}), 200


@admin_webhooks_bp.route("/<webhook_id>", methods=["GET"])
@require_auth
@require_permission(PERM_MANAGE)
def get_webhook(webhook_id):
    """Return one endpoint with its recent delivery history."""
    service = _build_service()
    endpoint = service.get(webhook_id)
    if endpoint is None:
        return jsonify({"error": "webhook not found"}), 404
    body = endpoint.to_dict()
    body["delivery_history"] = [
        delivery.to_dict()
        for delivery in service.list_deliveries(
            webhook_id, limit=_DELIVERY_HISTORY_LIMIT
        )
    ]
    return jsonify({"webhook": body}), 200


@admin_webhooks_bp.route("", methods=["POST"])
@require_auth
@require_permission(PERM_MANAGE)
def create_webhook():
    """Create a endpoint (generates a secret when none supplied)."""
    data = request.get_json() or {}
    url = data.get("url")
    events = data.get("events") or []
    if not url:
        return jsonify({"error": "url is required"}), 400
    service = _build_service()
    try:
        endpoint = service.create(
            url=url,
            event_types=events,
            secret=data.get("secret"),
            description=data.get("description"),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"webhook": endpoint.to_dict()}), 201


@admin_webhooks_bp.route("/<webhook_id>", methods=["PUT"])
@require_auth
@require_permission(PERM_MANAGE)
def update_webhook(webhook_id):
    """Update a endpoint's url / events / description."""
    data = request.get_json() or {}
    service = _build_service()
    try:
        endpoint = service.update(
            webhook_id,
            url=data.get("url"),
            event_types=data.get("events"),
            description=data.get("description"),
        )
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"webhook": endpoint.to_dict()}), 200


@admin_webhooks_bp.route("/<webhook_id>", methods=["DELETE"])
@require_auth
@require_permission(PERM_MANAGE)
def delete_webhook(webhook_id):
    """Delete a endpoint (cascades its deliveries)."""
    service = _build_service()
    service.delete(webhook_id)
    return jsonify({"status": "deleted"}), 200


@admin_webhooks_bp.route("/<webhook_id>/toggle", methods=["POST"])
@require_auth
@require_permission(PERM_MANAGE)
def toggle_webhook(webhook_id):
    """Flip a endpoint's active state."""
    service = _build_service()
    try:
        endpoint = service.toggle(webhook_id)
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify({"webhook": endpoint.to_dict()}), 200


@admin_webhooks_bp.route("/<webhook_id>/test", methods=["POST"])
@require_auth
@require_permission(PERM_MANAGE)
def test_webhook(webhook_id):
    """Deliver a synthetic ``webhook.test`` event to the endpoint now."""
    service = _build_service()
    try:
        delivery = service.send_test(webhook_id)
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify({"delivery": delivery.to_dict()}), 200
