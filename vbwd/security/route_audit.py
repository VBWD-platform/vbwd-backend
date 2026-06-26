"""Route-exposure introspection helper (S90, slice 1 — the keystone).

Walks a fully-booted Flask ``app.url_map`` and reports, per registered rule,
how it is protected: whether it carries the ``requires_auth`` marker (from
``@require_auth``), whether it carries a ``required_permission`` marker (from
``@require_permission`` / ``@require_user_permission``), and whether it is
gated by ``@require_debug_enabled`` (hidden 404 in production).

This module is **pure introspection**: it returns structured data and never
asserts. The route-exposure oracle (the test) layers the allow-list policy on
top of this data, and the future ``flask prod-readiness`` command reuses the
same walk — so the classification logic lives in exactly one place (DRY).

It is core-agnostic: it reads only the generic markers that core middleware
stamps on view functions; it imports no plugin and reads no domain field.
"""
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Set

from flask import Flask

# Methods Werkzeug adds to every rule implicitly; not part of the exposed
# contract, so they are excluded from the reported method set.
IMPLICIT_METHODS: Set[str] = {"HEAD", "OPTIONS"}

# Methods that change server state; mutating routes are held to the stricter
# "auth AND permission" bar by the oracle.
MUTATING_METHODS: Set[str] = {"POST", "PUT", "PATCH", "DELETE"}

# Marker attribute names stamped by the core decorators. Kept here as named
# constants so the helper, the oracle, and the readiness command agree on the
# exact attribute strings (single source of truth).
REQUIRES_AUTH_MARKER = "requires_auth"
REQUIRED_PERMISSION_MARKER = "required_permission"
REQUIRES_DEBUG_MARKER = "requires_debug_enabled"
REQUIRES_ADMIN_MARKER = "requires_admin"


@dataclass(frozen=True)
class RouteAudit:
    """Protection facts for a single (rule, method-set) registered route."""

    path: str
    endpoint: str
    methods: List[str]
    requires_auth: bool
    required_permission: Optional[str]
    requires_admin: bool
    requires_debug_enabled: bool

    @property
    def is_mutating(self) -> bool:
        """True if any exposed method changes server state."""
        return bool(set(self.methods) & MUTATING_METHODS)

    @property
    def is_authorization_gated(self) -> bool:
        """True if an explicit authorisation gate (RBAC permission or admin).

        Authentication alone (``requires_auth``) means "a logged-in user"; an
        authorisation gate additionally restricts *which* logged-in user. Used
        by the oracle to hold privileged mutations to the stricter bar while
        accepting authenticated self-service mutations.
        """
        return self.required_permission is not None or self.requires_admin

    @property
    def methods_label(self) -> str:
        """Human-readable method list, e.g. ``GET,POST``."""
        return ",".join(self.methods)


def _iter_decorator_chain(view_func: Any) -> Iterator[Any]:
    """Yield the view function and every ``@wraps``-linked inner function.

    Auth/permission/debug decorators stamp markers on their own wrapper, so a
    marker may live on any link of the ``__wrapped__`` chain rather than only
    on the outermost view function.
    """
    seen: Set[int] = set()
    current = view_func
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = getattr(current, "__wrapped__", None)


def inspect_view(view_func: Any) -> tuple[bool, Optional[str], bool, bool]:
    """Return ``(requires_auth, required_permission, requires_admin, requires_debug)``.

    Scans the decorator chain of ``view_func`` for the core markers. A present
    permission or admin marker also implies authentication (those decorators
    run after ``@require_auth``).
    """
    requires_auth = False
    required_permission: Optional[str] = None
    requires_admin = False
    requires_debug_enabled = False

    for link in _iter_decorator_chain(view_func):
        if getattr(link, REQUIRES_AUTH_MARKER, False):
            requires_auth = True
        link_permission = getattr(link, REQUIRED_PERMISSION_MARKER, None)
        if link_permission is not None:
            required_permission = link_permission
            requires_auth = True
        if getattr(link, REQUIRES_ADMIN_MARKER, False):
            requires_admin = True
            requires_auth = True
        if getattr(link, REQUIRES_DEBUG_MARKER, False):
            requires_debug_enabled = True

    return requires_auth, required_permission, requires_admin, requires_debug_enabled


def audit_routes(app: Flask) -> List[RouteAudit]:
    """Return one :class:`RouteAudit` per registered rule on ``app``.

    Pure: walks ``app.url_map`` and the registered view functions, applying no
    policy. The caller (oracle / readiness command) decides what is acceptable.
    """
    audits: List[RouteAudit] = []
    for rule in app.url_map.iter_rules():
        view_func = app.view_functions.get(rule.endpoint)
        (
            requires_auth,
            required_permission,
            requires_admin,
            requires_debug,
        ) = inspect_view(view_func)
        methods = sorted((rule.methods or set()) - IMPLICIT_METHODS)
        audits.append(
            RouteAudit(
                path=str(rule),
                endpoint=rule.endpoint,
                methods=methods,
                requires_auth=requires_auth,
                required_permission=required_permission,
                requires_admin=requires_admin,
                requires_debug_enabled=requires_debug,
            )
        )
    return audits


# ---------------------------------------------------------------------------
# Route-exposure policy — the single source of truth shared by the oracle test
# AND the ``flask prod-readiness`` command (DRY). A route that is neither
# protected nor allow-listed is an "unprotected route" — the G1 exposure.
# ---------------------------------------------------------------------------

# Privileged URL prefixes. A MUTATING route under one of these must be
# authorisation-gated (an RBAC @require_permission or @require_admin), not just
# authenticated — these are management surfaces, never self-service.
PRIVILEGED_PREFIXES = ("/api/v1/admin/",)

# PUBLIC_ALLOWLIST — routes that are public BY DESIGN (read or mutation alike).
# A route here does not need the requires_auth marker. Each entry carries a
# one-line justification; adding one is a reviewed decision.
# Keyed by the exact Werkzeug rule template (str(rule)).
PUBLIC_ALLOWLIST: Dict[str, str] = {
    # --- App liveness / infra (no data) -----------------------------------
    "/": "Root liveness ping; returns a static banner, no data.",
    "/api/v1/health": "Liveness probe for load balancers; no data.",
    "/api/v1/ready": "Readiness probe for orchestrators; no data.",
    "/static/<path:filename>": "Flask static asset serving; public files only.",
    "/uploads/<path:filename>": "Public CMS upload serving; published media only.",
    # --- Public site config (needed before login) -------------------------
    "/api/v1/config": "Public app config (currency, languages) for the SPA shell.",
    "/api/v1/config/": "Public app config (trailing-slash variant of the above).",
    "/api/v1/config/languages": "Public list of available UI languages.",
    # --- Auth pre-login reads ---------------------------------------------
    "/api/v1/auth/check-email": "Pre-registration email-availability check; public by necessity.",
    # --- Public settings reads (checkout/registration need these) ---------
    "/api/v1/settings/countries": "Public country list for address/registration forms.",
    "/api/v1/settings/payment-methods": "Public enabled-payment-methods list for checkout.",
    "/api/v1/settings/payment-methods/<code>": "Public single-payment-method lookup for checkout.",
    "/api/v1/settings/terms": "Public terms-and-conditions text for registration/checkout.",
    # --- Public catalog reads (product browsing, pre-login) ---------------
    "/api/v1/token-bundles/": "Public token-bundle catalog for the storefront.",
    "/api/v1/token-bundles/<bundle_id>": "Public single token-bundle detail for the storefront.",
    "/api/v1/tarif-plans": "Public subscription-plan catalog for pricing pages.",
    "/api/v1/tarif-plans/<slug_or_id>": "Public single subscription-plan detail.",
    "/api/v1/addons/": "Public subscription add-on catalog for pricing pages.",
    "/api/v1/addons/<addon_id>": "Public single add-on detail.",
    "/api/v1/subscription/public/checkout-draft/<token>": "Checkout-draft resolve; the token is the capability.",
    "/api/v1/shop/categories": "Public shop category listing for the storefront.",
    "/api/v1/shop/categories/<slug>": "Public single shop category for the storefront.",
    "/api/v1/shop/products": "Public shop product listing for the storefront.",
    "/api/v1/shop/products/<slug>": "Public single shop product for the storefront.",
    "/api/v1/pharma/catalogue": "Public pharma-shop catalogue listing for the storefront.",
    "/api/v1/pharma/products/<slug>": "Public single pharma-shop product for the storefront.",
    "/api/v1/pharma/region": "Public pharma-shop region/availability info for the storefront.",
    "/api/v1/booking/categories": "Public booking category listing for the storefront.",
    "/api/v1/booking/config": "Public booking widget config for the storefront.",
    "/api/v1/booking/resources": "Public bookable-resource listing for the storefront.",
    "/api/v1/booking/resources/<slug>": "Public single bookable resource for the storefront.",
    "/api/v1/booking/resources/<slug>/availability": "Public availability lookup for booking UI.",
    "/api/v1/booking/schemas": "Public booking form schemas for the storefront.",
    "/api/v1/ghrm/categories": "Public GHRM marketplace category listing.",
    "/api/v1/ghrm/config": "Public GHRM marketplace config for the storefront.",
    "/api/v1/ghrm/packages": "Public GHRM software-package listing.",
    "/api/v1/ghrm/packages/<slug>": "Public single GHRM package detail.",
    "/api/v1/ghrm/packages/<slug>/related": "Public related-packages list for a GHRM package.",
    "/api/v1/ghrm/packages/<slug>/versions": "Public version history for a GHRM package.",
    "/api/v1/ghrm/packages/by-plan/<plan_id>": "Public GHRM package lookup by plan id.",
    "/api/v1/ghrm/widgets": "Public GHRM storefront widgets.",
    "/api/v1/loopai-adapter/posts": "Public published-post listing for the LoopAI WP adapter.",
    "/api/v1/tarot/assets/arcana/<path:filename>": "Public static tarot-card image assets.",
    "/api/v1/bot-conversation-style/active": "Public active chat-bot conversation style for the widget.",
    "/api/v1/messaging/stream": "SSE stream; auth'd by a verified stream_token query param (EventSource: no headers).",
    # --- Public CMS reads (the public website) ----------------------------
    "/api/v1/cms/categories": "Public CMS category listing for the website.",
    "/api/v1/cms/embed-manifest": "Public mobile validation probe before pointing a WebView at the CMS archive (S91).",
    "/api/v1/cms/layouts/<layout_id>": "Public CMS layout for page rendering.",
    "/api/v1/cms/layouts/by-slug/<slug>": "Public CMS layout by slug for page rendering.",
    "/api/v1/cms/posts": "Public published-CMS-posts listing for the website/blog.",
    "/api/v1/cms/posts/<path:slug>": "Public published CMS post by slug.",
    "/api/v1/cms/routing-rules": "Public CMS routing rules for the SPA router.",
    "/api/v1/cms/routing-rules/middleware": "Public CMS middleware routing rules for the SPA router.",
    "/api/v1/cms/rss.xml": "Public RSS feed for the blog.",
    "/api/v1/cms/search": "Public CMS post search for the website.",
    "/api/v1/cms/styles/<style_id>/css": "Public CMS style CSS for page rendering.",
    "/api/v1/cms/styles/default": "Public default CMS style descriptor.",
    "/api/v1/cms/styles/default/css": "Public default CMS style CSS.",
    "/api/v1/cms/terms": "Public CMS taxonomy terms for the website.",
    "/robots.txt": "Public robots.txt for crawlers.",
    "/sitemap.xml": "Public sitemap index for crawlers.",
    "/sitemap-<int:chunk>.xml": "Public paginated sitemap chunk for crawlers.",
}

# PUBLIC_MUTATION_ALLOWLIST — mutating routes (POST/PUT/PATCH/DELETE) that are
# public BY NECESSITY: pre-login auth flows, provider webhooks, and public
# forms. These are exempt from the "must carry a required_permission marker"
# rule. Deliberately tiny; each entry justified.
PUBLIC_MUTATION_ALLOWLIST: Dict[str, str] = {
    # --- Auth flows (cannot require a logged-in user) ---------------------
    "/api/v1/auth/login": "Login must be reachable pre-auth; rate-limited (G5).",
    "/api/v1/auth/register": "Registration must be reachable pre-auth; rate-limited (G5).",
    "/api/v1/auth/logout": "Logout endpoint; pre-/post-auth tolerant.",
    "/api/v1/auth/forgot-password": "Password-reset request must be reachable pre-auth.",
    "/api/v1/auth/reset-password": "Password reset consumes a one-time token (the capability).",
    # --- Payment provider webhooks (signature-validated in handler, G5) ---
    # The core /api/v1/webhooks/payment "manually mark invoice paid" tool is now
    # @require_auth + @require_permission("invoices.manage") (S90 DoD #7 / G5), so
    # the oracle classifies it as authorisation-gated — it is intentionally NOT
    # allow-listed here. Only the static reachability probe stays public.
    "/api/v1/webhooks/payment/test": "Reachability probe; returns a static ok, no state change.",
    "/api/v1/plugins/paypal/webhook": "PayPal provider webhook; verified by PayPal signature in handler.",
    "/api/v1/plugins/stripe/webhook": "Stripe provider webhook; verified by Stripe signature in handler.",
    "/api/v1/plugins/yookassa/webhook": "YooKassa provider webhook; verified by provider signature in handler.",
    "/api/v1/plugins/conekta/webhooks": "Conekta provider webhook; verified by provider signature in handler.",
    "/api/v1/plugins/mercado-pago/webhooks/<country>": "Mercado Pago provider webhook; verified by provider signature.",
    "/api/v1/plugins/promptpay/webhooks/<bank>": "PromptPay bank webhook; verified by provider signature in handler.",
    "/api/v1/plugins/toss-payments/webhooks": "Toss Payments provider webhook; verified by provider signature.",
    "/api/v1/plugins/truemoney/webhooks": "TrueMoney provider webhook; verified by provider signature in handler.",
    "/api/v1/plugins/c2p2/backend-notifications": "C2P2 provider backend notification; signature-verified in handler.",
    "/api/v1/plugins/bot-telegram/webhook/<bot>": "Telegram bot webhook; per-bot secret path is the capability.",
    "/api/v1/ghrm/sync": "GHRM CI sync trigger; authenticated by an API key validated inside the handler.",
    # --- Admin mutations gated by a DYNAMIC (registry-driven) permission --
    # These carry @require_auth and enforce the entity type's per-registration
    # `manage_permission` in-handler via `_require_entity_manage`, which a
    # static @require_permission(...) decorator cannot express (the required
    # permission depends on the runtime <entity_type>). Authorisation-gated,
    # just not via the static marker — so allow-listed with this justification.
    "/api/v1/admin/<entity_type>/<entity_id>/tags": "Admin tag write; manage_permission enforced in-handler.",
    "/api/v1/admin/<entity_type>/<entity_id>/custom-fields": "Admin custom-field write; manage_permission in-handler.",
    # --- Public forms / public widget actions -----------------------------
    "/api/v1/contact": "Public contact form submission (no account required).",
    "/api/v1/coupons/validate": "Public coupon validation for checkout (read-like, no mutation persisted).",
    "/api/v1/messaging/widget/start": "Public chat-widget conversation start (anonymous visitor support).",
}


def classify_unprotected_routes(audits: List[RouteAudit]) -> List[RouteAudit]:
    """Return the offender audits (empty == every route is provably protected).

    Contract per route:

    * **Read-only route** is OK iff it carries the ``requires_auth`` marker, is
      debug-gated (404 in prod), OR is in :data:`PUBLIC_ALLOWLIST`.
    * **Mutating route** (POST/PUT/PATCH/DELETE) is OK iff it is in
      :data:`PUBLIC_MUTATION_ALLOWLIST` OR it carries ``requires_auth`` — and,
      when it lives under a privileged prefix (``/admin/``), it must additionally
      be authorisation-gated (an RBAC permission or admin marker). Authenticated
      self-service mutations are OK with ``requires_auth`` alone.
    * A mutating route with **no auth at all** and not allow-listed is the G1
      exposure this guard exists to catch.
    """
    offenders: List[RouteAudit] = []
    for route in audits:
        if route.is_mutating:
            if route.path in PUBLIC_MUTATION_ALLOWLIST:
                continue
            if not route.requires_auth:
                offenders.append(route)
                continue
            is_privileged = any(
                route.path.startswith(prefix) for prefix in PRIVILEGED_PREFIXES
            )
            if is_privileged and not route.is_authorization_gated:
                offenders.append(route)
            continue

        # Read-only route: auth marker, debug-gating (404 in prod), OR a
        # public allow-list entry.
        if route.requires_auth or route.requires_debug_enabled:
            continue
        if route.path in PUBLIC_ALLOWLIST:
            continue
        offenders.append(route)
    return offenders


def find_unprotected_routes(app: Flask) -> List[RouteAudit]:
    """Audit ``app`` and return the routes that are neither protected nor
    deliberately allow-listed (empty list == all protected).

    The single seam reused by the route-exposure oracle test and the
    ``flask prod-readiness`` command (DRY).
    """
    return classify_unprotected_routes(audit_routes(app))


def describe_offender(route: RouteAudit) -> str:
    """Human-readable one-line description of why ``route`` is an offender."""
    if (
        route.is_mutating
        and route.requires_auth
        and any(route.path.startswith(prefix) for prefix in PRIVILEGED_PREFIXES)
        and not route.is_authorization_gated
    ):
        return (
            f"{route.methods_label} {route.path}  "
            "(admin mutation: @require_auth present but no "
            "@require_permission / @require_admin)"
        )
    return f"{route.methods_label} {route.path}  (no @require_auth / not allow-listed)"


def _route_namespace(path: str) -> str:
    """The plugin/area namespace a route path belongs to.

    ``/api/v1/plugins/<name>/...`` → ``api/v1/plugins/<name>`` and
    ``/api/v1/<area>/...`` → ``api/v1/<area>``. Used to tell "this route was
    removed/renamed" (its namespace still has live siblings) apart from "the
    plugin that owns it simply isn't loaded in this configuration".
    """
    parts = [segment for segment in path.split("/") if segment]
    if len(parts) >= 4 and parts[2] == "plugins":
        return "/".join(parts[:4])
    if len(parts) >= 3:
        return "/".join(parts[:3])
    return "/".join(parts)


def find_stale_allowlist_entries(app: Flask) -> List[str]:
    """Return allow-list entries that no longer match a live rule on ``app``.

    Keeps the allow-lists from rotting: a removed/renamed public route forces a
    reviewed cleanup instead of lingering as a phantom exemption.

    The allow-lists are the central registry for EVERY public route across all
    plugins, but a given app may boot only a subset (e.g. the core ``Tests`` CI
    installs an active set without the regional payment plugins). An entry whose
    owning namespace is entirely absent from the live url_map belongs to a
    plugin that isn't loaded here — that is not rot, so it is skipped. An entry
    whose namespace IS live but whose specific route is gone is genuinely stale
    and still reported, so removing/renaming a public route on a loaded plugin
    is caught.
    """
    live_paths = {route.path for route in audit_routes(app)}
    live_namespaces = {_route_namespace(path) for path in live_paths}

    def _is_stale(path: str) -> bool:
        return path not in live_paths and _route_namespace(path) in live_namespaces

    stale = [
        f"PUBLIC_ALLOWLIST: {path}"
        for path in sorted(PUBLIC_ALLOWLIST)
        if _is_stale(path)
    ]
    stale += [
        f"PUBLIC_MUTATION_ALLOWLIST: {path}"
        for path in sorted(PUBLIC_MUTATION_ALLOWLIST)
        if _is_stale(path)
    ]
    return stale
