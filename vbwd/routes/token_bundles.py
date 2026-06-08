"""Public token bundle routes (for user checkout)."""
from flask import Blueprint, current_app, jsonify
from vbwd.repositories.token_bundle_repository import TokenBundleRepository
from vbwd.services.cache import cached_response, resolve_cache_store
from vbwd.extensions import db

token_bundles_bp = Blueprint(
    "token_bundles", __name__, url_prefix="/api/v1/token-bundles"
)

# Cache key family for the public token-bundle list. Admin bundle writes clear
# this whole prefix so an edit is reflected immediately (TTL is the backstop).
TOKEN_BUNDLES_CACHE_PREFIX = "token-bundles:"
TOKEN_BUNDLES_LIST_CACHE_KEY = f"{TOKEN_BUNDLES_CACHE_PREFIX}list"


def _catalog_ttl_seconds() -> int:
    return int(current_app.config.get("CACHE_TTL_SECONDS", 120))


def invalidate_token_bundle_cache() -> None:
    """Clear the cached public token-bundle list (call after any admin write)."""
    resolve_cache_store().delete_prefix(TOKEN_BUNDLES_CACHE_PREFIX)


@token_bundles_bp.route("/", methods=["GET"])
def list_active_bundles():
    """
    List all active token bundles (public endpoint).

    This endpoint is used for the user checkout flow to display
    available token bundles that can be added to the order.

    Returns:
        200: List of active token bundles
    """

    def produce_bundle_list():
        bundle_repo = TokenBundleRepository(db.session)
        bundles = bundle_repo.find_active()
        return {"bundles": [bundle.to_dict() for bundle in bundles]}, 200

    body, status = cached_response(
        resolve_cache_store(),
        TOKEN_BUNDLES_LIST_CACHE_KEY,
        _catalog_ttl_seconds(),
        produce_bundle_list,
    )
    return jsonify(body), status


@token_bundles_bp.route("/<bundle_id>", methods=["GET"])
def get_token_bundle(bundle_id):
    """
    Get token bundle details by ID (public catalog endpoint).

    Args:
        bundle_id: UUID of the token bundle

    Returns:
        200: Token bundle details
        404: Token bundle not found
    """
    try:
        bundle_repo = TokenBundleRepository(db.session)
        bundle = bundle_repo.find_by_id(bundle_id)
    except Exception:
        return jsonify({"error": "Token bundle not found"}), 404

    if not bundle:
        return jsonify({"error": "Token bundle not found"}), 404

    return jsonify({"bundle": bundle.to_dict()}), 200
