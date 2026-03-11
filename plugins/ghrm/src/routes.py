"""GHRM plugin API routes.

Public (no auth):
    GET  /api/v1/ghrm/packages                 list packages
    GET  /api/v1/ghrm/packages/<slug>          package detail
    GET  /api/v1/ghrm/packages/<slug>/related  related packages
    GET  /api/v1/ghrm/packages/<slug>/versions versions list
    GET  /api/v1/ghrm/sync                     GitHub Action sync trigger (API key auth)

Subscriber-only:
    GET  /api/v1/ghrm/packages/<slug>/install  install instructions

GitHub OAuth (requires_auth):
    GET    /api/v1/ghrm/auth/github            redirect to github.com/oauth/authorize
    POST   /api/v1/ghrm/auth/github/callback   exchange code + store identity
    DELETE /api/v1/ghrm/auth/github            disconnect GitHub

User profile (requires_auth):
    GET  /api/v1/ghrm/access                   current github access status

Admin (require_admin):
    GET    /api/v1/admin/ghrm/packages
    POST   /api/v1/admin/ghrm/packages
    PUT    /api/v1/admin/ghrm/packages/<id>
    DELETE /api/v1/admin/ghrm/packages/<id>
    POST   /api/v1/admin/ghrm/packages/<id>/rotate-key
    POST   /api/v1/admin/ghrm/packages/<id>/sync
    GET    /api/v1/admin/ghrm/access-log
    POST   /api/v1/admin/ghrm/access/sync/<user_id>
"""
import logging
import uuid
import secrets
from flask import Blueprint, jsonify, request, redirect, g, current_app
from src.extensions import db
from src.middleware.auth import require_auth, require_admin

from plugins.ghrm.src.repositories.software_package_repository import GhrmSoftwarePackageRepository
from plugins.ghrm.src.repositories.software_sync_repository import GhrmSoftwareSyncRepository
from plugins.ghrm.src.repositories.user_github_access_repository import GhrmUserGithubAccessRepository
from plugins.ghrm.src.repositories.access_log_repository import GhrmAccessLogRepository
from plugins.ghrm.src.services.software_package_service import (
    SoftwarePackageService, GhrmPackageNotFoundError, GhrmSyncAuthError, GhrmSubscriptionRequiredError,
)
from plugins.ghrm.src.services.github_access_service import (
    GithubAccessService, GhrmOAuthError, GhrmGithubNotConnectedError,
)
from plugins.ghrm.src.services.github_app_client import MockGithubAppClient
from plugins.ghrm.src.models.ghrm_software_package import GhrmSoftwarePackage

logger = logging.getLogger(__name__)
ghrm_bp = Blueprint("ghrm", __name__)


# ─── Dependency factories ────────────────────────────────────────────────────

def _pkg_svc() -> SoftwarePackageService:
    cfg = _cfg()
    return SoftwarePackageService(
        package_repo=GhrmSoftwarePackageRepository(db.session),
        sync_repo=GhrmSoftwareSyncRepository(db.session),
        github=MockGithubAppClient(),
        software_category_slugs=cfg.get("software_category_slugs", []),
    )


def _access_svc() -> GithubAccessService:
    cfg = _cfg()
    return GithubAccessService(
        access_repo=GhrmUserGithubAccessRepository(db.session),
        log_repo=GhrmAccessLogRepository(db.session),
        package_repo=GhrmSoftwarePackageRepository(db.session),
        github=MockGithubAppClient(),
        oauth_client_id=cfg.get("github_oauth_client_id", ""),
        oauth_client_secret=cfg.get("github_oauth_client_secret", ""),
        oauth_redirect_uri=cfg.get("github_oauth_redirect_uri", ""),
        grace_period_fallback_days=cfg.get("grace_period_fallback_days", 7),
    )


def _cfg() -> dict:
    try:
        from src.plugins.manager import plugin_manager
        plugin = plugin_manager.get_plugin("ghrm")
        return plugin.config or {} if plugin else {}
    except Exception:
        return {}


# ─── Public catalogue ────────────────────────────────────────────────────────

@ghrm_bp.route("/api/v1/ghrm/packages", methods=["GET"])
def list_packages():
    """List active software packages."""
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    category_slug = request.args.get("category_slug") or None
    query = request.args.get("q") or None
    result = _pkg_svc().list_packages(page=page, per_page=per_page, category_slug=category_slug, query=query)
    return jsonify(result)


@ghrm_bp.route("/api/v1/ghrm/packages/<slug>", methods=["GET"])
def get_package(slug):
    """Get package detail with merged cached/override data."""
    try:
        data = _pkg_svc().get_package(slug)
        return jsonify(data)
    except GhrmPackageNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@ghrm_bp.route("/api/v1/ghrm/packages/<slug>/related", methods=["GET"])
def get_related(slug):
    try:
        return jsonify(_pkg_svc().get_related(slug))
    except GhrmPackageNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@ghrm_bp.route("/api/v1/ghrm/packages/<slug>/versions", methods=["GET"])
def get_versions(slug):
    try:
        return jsonify(_pkg_svc().get_versions(slug))
    except GhrmPackageNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@ghrm_bp.route("/api/v1/ghrm/packages/<slug>/install", methods=["GET"])
@require_auth
def get_install(slug):
    """Return install instructions — requires active subscription + GitHub connection."""
    user_id = g.user_id
    # Fetch deploy_token directly from repo (not exposed in to_dict())
    raw = GhrmUserGithubAccessRepository(db.session).find_by_user_id(user_id)
    token = raw.deploy_token if raw else None
    try:
        return jsonify(_pkg_svc().get_install_instructions(slug, user_id, deploy_token=token))
    except GhrmPackageNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except GhrmSubscriptionRequiredError as e:
        return jsonify({"error": str(e)}), 403


# ─── Sync endpoint (GitHub Action) ──────────────────────────────────────────

@ghrm_bp.route("/api/v1/ghrm/sync", methods=["GET", "POST"])
def sync_package():
    """Triggered by GitHub Action: ?package=<slug>&key=<api_key>"""
    api_key = request.args.get("key") or (request.json or {}).get("key", "")
    try:
        result = _pkg_svc().sync_package(api_key)
        return jsonify({"ok": True, "sync": result})
    except GhrmSyncAuthError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        logger.error(f"[GHRM] sync error: {e}", exc_info=True)
        return jsonify({"error": "Sync failed"}), 500


# ─── GitHub OAuth ────────────────────────────────────────────────────────────

@ghrm_bp.route("/api/v1/ghrm/auth/github", methods=["GET"])
@require_auth
def github_oauth_start():
    """Build and return the GitHub OAuth URL (client does the redirect)."""
    import jwt as pyjwt
    import time
    user_id = g.user_id
    nonce = secrets.token_urlsafe(16)
    # Store nonce in Redis with 10-min TTL
    try:
        from src.extensions import redis_client
        redis_client.setex(f"ghrm:oauth:nonce:{user_id}", 600, nonce)
    except Exception:
        pass
    state = pyjwt.encode(
        {"user_id": user_id, "nonce": nonce, "exp": int(time.time()) + 600},
        current_app.config.get("JWT_SECRET_KEY", "dev"),
        algorithm="HS256",
    )
    url = _access_svc().get_oauth_url(user_id, state)
    return jsonify({"url": url})


@ghrm_bp.route("/api/v1/ghrm/auth/github/callback", methods=["POST"])
@require_auth
def github_oauth_callback():
    """Exchange OAuth code, verify CSRF state, store GitHub identity."""
    import jwt as pyjwt
    user_id = g.user_id
    body = request.json or {}
    code = body.get("code", "")
    state = body.get("state", "")
    # Verify state JWT
    try:
        payload = pyjwt.decode(state, current_app.config.get("JWT_SECRET_KEY", "dev"), algorithms=["HS256"])
        if str(payload.get("user_id")) != str(user_id):
            return jsonify({"error": "State mismatch"}), 400
        # Verify nonce
        nonce = payload.get("nonce", "")
        try:
            from src.extensions import redis_client
            stored = redis_client.get(f"ghrm:oauth:nonce:{user_id}")
            if not stored or stored.decode() != nonce:
                return jsonify({"error": "Invalid or expired state"}), 400
            redis_client.delete(f"ghrm:oauth:nonce:{user_id}")
        except Exception:
            pass
    except pyjwt.ExpiredSignatureError:
        return jsonify({"error": "State expired"}), 400
    except pyjwt.InvalidTokenError:
        return jsonify({"error": "Invalid state"}), 400
    try:
        result = _access_svc().handle_oauth_callback(user_id, code)
        return jsonify(result)
    except GhrmOAuthError as e:
        return jsonify({"error": str(e)}), 502


@ghrm_bp.route("/api/v1/ghrm/auth/github", methods=["DELETE"])
@require_auth
def github_disconnect():
    """Disconnect GitHub — revoke token and remove collaborator."""
    _access_svc().disconnect_github(g.user_id)
    return jsonify({"ok": True})


# ─── User profile ────────────────────────────────────────────────────────────

@ghrm_bp.route("/api/v1/ghrm/access", methods=["GET"])
@require_auth
def get_access_status():
    result = _access_svc().get_access_status(g.user_id)
    if not result:
        return jsonify({"connected": False}), 200
    return jsonify({**result, "connected": True})


# ─── Admin endpoints ─────────────────────────────────────────────────────────

@ghrm_bp.route("/api/v1/admin/ghrm/packages", methods=["GET"])
@require_admin
def admin_list_packages():
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    query = request.args.get("q") or None
    repo = GhrmSoftwarePackageRepository(db.session)
    result = repo.find_all(page=page, per_page=per_page, query=query)
    result["items"] = [p.to_dict() for p in result["items"]]
    return jsonify(result)


@ghrm_bp.route("/api/v1/admin/ghrm/packages", methods=["POST"])
@require_admin
def admin_create_package():
    body = request.json or {}
    required = ("name", "slug", "github_owner", "github_repo", "tariff_plan_id")
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    repo = GhrmSoftwarePackageRepository(db.session)
    if repo.find_by_slug(body["slug"]):
        return jsonify({"error": "Slug already exists"}), 409
    pkg = GhrmSoftwarePackage(
        tariff_plan_id=body["tariff_plan_id"],
        name=body["name"],
        slug=body["slug"],
        author_name=body.get("author_name"),
        icon_url=body.get("icon_url"),
        github_owner=body["github_owner"],
        github_repo=body["github_repo"],
        github_protected_branch=body.get("github_protected_branch", "release"),
        tech_specs=body.get("tech_specs", {}),
        related_slugs=body.get("related_slugs", []),
        sort_order=body.get("sort_order", 0),
    )
    repo.save(pkg)
    return jsonify(pkg.to_dict()), 201


@ghrm_bp.route("/api/v1/admin/ghrm/packages/<pkg_id>", methods=["PUT"])
@require_admin
def admin_update_package(pkg_id):
    repo = GhrmSoftwarePackageRepository(db.session)
    pkg = repo.find_by_id(pkg_id)
    if not pkg:
        return jsonify({"error": "Not found"}), 404
    body = request.json or {}
    updatable = ("name", "author_name", "icon_url", "github_owner", "github_repo",
                 "github_protected_branch", "tech_specs", "related_slugs", "sort_order", "is_active")
    for field in updatable:
        if field in body:
            setattr(pkg, field, body[field])
    # Sync overrides
    if any(k in body for k in ("override_readme", "override_changelog", "override_docs", "admin_screenshots")):
        sync_repo = GhrmSoftwareSyncRepository(db.session)
        sync = sync_repo.find_by_package_id(pkg_id)
        if sync:
            for field in ("override_readme", "override_changelog", "override_docs", "admin_screenshots"):
                if field in body:
                    setattr(sync, field, body[field])
            sync_repo.save(sync)
    repo.save(pkg)
    return jsonify(pkg.to_dict())


@ghrm_bp.route("/api/v1/admin/ghrm/packages/<pkg_id>", methods=["DELETE"])
@require_admin
def admin_delete_package(pkg_id):
    repo = GhrmSoftwarePackageRepository(db.session)
    if not repo.delete(pkg_id):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@ghrm_bp.route("/api/v1/admin/ghrm/packages/<pkg_id>/rotate-key", methods=["POST"])
@require_admin
def admin_rotate_key(pkg_id):
    try:
        new_key = _pkg_svc().rotate_api_key(pkg_id)
        return jsonify({"sync_api_key": new_key})
    except GhrmPackageNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@ghrm_bp.route("/api/v1/admin/ghrm/packages/<pkg_id>/sync", methods=["POST"])
@require_admin
def admin_sync_package(pkg_id):
    repo = GhrmSoftwarePackageRepository(db.session)
    pkg = repo.find_by_id(pkg_id)
    if not pkg:
        return jsonify({"error": "Not found"}), 404
    try:
        result = _pkg_svc().sync_package(pkg.sync_api_key)
        return jsonify({"ok": True, "sync": result})
    except Exception as e:
        logger.error(f"[GHRM] admin sync error: {e}", exc_info=True)
        return jsonify({"error": "Sync failed"}), 500


@ghrm_bp.route("/api/v1/admin/ghrm/access-log", methods=["GET"])
@require_admin
def admin_access_log():
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    user_id = request.args.get("user_id")
    log_repo = GhrmAccessLogRepository(db.session)
    if user_id:
        result = log_repo.find_by_user(user_id, page=page, per_page=per_page)
    else:
        # All logs — query directly
        from plugins.ghrm.src.models.ghrm_access_log import GhrmAccessLog
        q = db.session.query(GhrmAccessLog).order_by(GhrmAccessLog.created_at.desc())
        total = q.count()
        items = q.offset((page - 1) * per_page).limit(per_page).all()
        result = {"items": [i.to_dict() for i in items], "total": total, "page": page, "per_page": per_page, "pages": max(1, (total + per_page - 1) // per_page)}
    return jsonify(result)


@ghrm_bp.route("/api/v1/admin/ghrm/access/sync/<user_id>", methods=["POST"])
@require_admin
def admin_sync_user_access(user_id):
    _access_svc().on_subscription_activated(user_id, "")
    return jsonify({"ok": True})
