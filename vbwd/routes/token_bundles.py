"""Public token bundle routes (for user checkout)."""
from flask import Blueprint, current_app, jsonify
from vbwd.pricing.display_mode import display_mode_fields
from vbwd.pricing.price_payload import build_pricing_block
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


def _bundle_dict_with_price(bundle) -> dict:
    """Serialise a token bundle with the computed ``Price`` block (S85.2).

    Routes the price math through the single core ``PriceFactory`` (D1) and
    embeds the serialized ``Price`` (``{netto, taxes, brutto, currency}``)
    alongside the existing fields — backward-compatible (the bare ``price``
    number stays). The display-mode pair (``effective_display_mode`` /
    ``prices_display_mode``) is added so the checkout/cart consumer can pick the
    net/gross side + the netto tag (S85.4).
    """
    bundle_dict = bundle.to_dict()
    # ``current_app.container`` is the DI container attached at app boot; mypy
    # cannot see the dynamic attribute on Flask (same as vbwd/routes/invoices.py).
    price_factory = current_app.container.price_factory()  # type: ignore[attr-defined]
    price = price_factory.get_price_from_object(bundle)
    bundle_dict["price_info"] = build_pricing_block(price)
    bundle_dict.update(display_mode_fields(bundle))
    return bundle_dict


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
        return {"bundles": [_bundle_dict_with_price(bundle) for bundle in bundles]}, 200

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

    return jsonify({"bundle": _bundle_dict_with_price(bundle)}), 200
