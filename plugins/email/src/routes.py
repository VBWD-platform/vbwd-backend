"""Email plugin admin routes.

All routes require admin authentication via @require_auth + @require_admin
(same pattern as src/routes/admin/).

Endpoints
---------
GET  /api/v1/admin/email/templates         — list all templates
GET  /api/v1/admin/email/templates/:id     — get one template
PUT  /api/v1/admin/email/templates/:id     — update template
POST /api/v1/admin/email/templates/preview — render preview (no delivery)
GET  /api/v1/admin/email/event-types       — list supported event types + variable schemas
POST /api/v1/admin/email/test-send         — send test email to given address
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from src.middleware.auth import require_auth, require_admin
from src.utils.validation import parse_uuid_or_none

email_bp = Blueprint("email", __name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _email_cfg() -> dict:
    """Return the email plugin config dict from the config store, or {}."""
    from flask import current_app

    config_store = getattr(current_app, "config_store", None)
    if config_store:
        cfg = config_store.get_config("email")
        if cfg:
            return cfg
    return {}


def _template_svc():
    from src.extensions import db
    from plugins.email.src.services.email_service import EmailService
    from plugins.email.src.services.sender_registry import EmailSenderRegistry
    from plugins.email.src.services.smtp_sender import SmtpEmailSender

    cfg = _email_cfg()
    registry = EmailSenderRegistry()
    smtp = SmtpEmailSender(
        host=cfg.get("smtp_host", "localhost"),
        port=int(cfg.get("smtp_port", 587)),
        username=cfg.get("smtp_user") or None,
        password=cfg.get("smtp_password") or None,
        use_tls=cfg.get("smtp_use_tls", True),
        from_address=cfg.get("smtp_from_email", "noreply@example.com"),
        from_name=cfg.get("smtp_from_name", "VBWD"),
    )
    registry.register(smtp)
    registry.set_active("smtp")
    return EmailService(registry=registry, db_session=db.session)


# ---------------------------------------------------------------------------
# List templates
# ---------------------------------------------------------------------------


@email_bp.route("/api/v1/admin/email/templates", methods=["GET"])
@require_auth
@require_admin
def list_templates():
    from src.extensions import db
    from plugins.email.src.models.email_template import EmailTemplate

    templates = db.session.query(EmailTemplate).order_by(EmailTemplate.event_type).all()
    return jsonify([t.to_dict() for t in templates]), 200


# ---------------------------------------------------------------------------
# Preview (must be before /<template_id> so Flask doesn't swallow "preview")
# ---------------------------------------------------------------------------


@email_bp.route("/api/v1/admin/email/templates/preview", methods=["POST"])
@require_auth
@require_admin
def preview_template():
    data = request.get_json(silent=True) or {}
    event_type = data.get("event_type", "")
    context = data.get("context", {})

    if not event_type:
        return jsonify({"error": "event_type required"}), 400

    svc = _template_svc()
    try:
        rendered = svc.render_preview(event_type, context)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 422

    return jsonify(rendered), 200


# ---------------------------------------------------------------------------
# Get / update by ID
# ---------------------------------------------------------------------------


@email_bp.route("/api/v1/admin/email/templates/<template_id>", methods=["GET"])
@require_auth
@require_admin
def get_template(template_id: str):
    if parse_uuid_or_none(template_id) is None:
        return jsonify({"error": "invalid id"}), 400
    from src.extensions import db
    from plugins.email.src.models.email_template import EmailTemplate

    tpl = db.session.get(EmailTemplate, template_id)
    if tpl is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(tpl.to_dict()), 200


@email_bp.route("/api/v1/admin/email/templates/<template_id>", methods=["PUT"])
@require_auth
@require_admin
def update_template(template_id: str):
    if parse_uuid_or_none(template_id) is None:
        return jsonify({"error": "invalid id"}), 400
    from src.extensions import db
    from plugins.email.src.models.email_template import EmailTemplate

    tpl = db.session.get(EmailTemplate, template_id)
    if tpl is None:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True) or {}
    allowed = {"subject", "html_body", "text_body", "is_active"}
    for field in allowed:
        if field in data:
            setattr(tpl, field, data[field])

    db.session.commit()
    return jsonify(tpl.to_dict()), 200


# ---------------------------------------------------------------------------
# Event-type catalogue
# ---------------------------------------------------------------------------


@email_bp.route("/api/v1/admin/email/event-types", methods=["GET"])
@require_auth
@require_admin
def list_event_types():
    # Import event_contexts to trigger auto-registration of core schemas, then
    # read the full registry (which also includes schemas from other plugins).
    import plugins.email.src.services.event_contexts  # noqa: F401
    from plugins.email.src.services.event_context_registry import get_all

    return jsonify(get_all()), 200


# ---------------------------------------------------------------------------
# Test send
# ---------------------------------------------------------------------------


@email_bp.route("/api/v1/admin/email/test-send", methods=["POST"])
@require_auth
@require_admin
def test_send():
    data = request.get_json(silent=True) or {}
    event_type = data.get("event_type")
    to_address = data.get("to_address")

    if not event_type or not to_address:
        return jsonify({"error": "event_type and to_address required"}), 400

    import plugins.email.src.services.event_contexts  # noqa: F401 — triggers auto-registration
    from plugins.email.src.services.event_context_registry import get as _get_ctx

    ctx_schema = _get_ctx(event_type) or {}
    preview_ctx = {
        k: v.get("example", "") for k, v in ctx_schema.get("variables", {}).items()
    }

    svc = _template_svc()
    try:
        sent = svc.send_event(event_type, to_address, preview_ctx)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502

    if not sent:
        return (
            jsonify({"message": "template inactive or not found, email not sent"}),
            200,
        )

    return jsonify({"message": f"test email sent to {to_address}"}), 200
