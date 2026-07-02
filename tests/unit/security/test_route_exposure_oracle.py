"""Route-exposure oracle (S90, slice 1 — the keystone).

Boots a fully-loaded app (core + all enabled plugins) and asserts that EVERY
registered route is provably either authentication-protected (carries the
``requires_auth`` marker) or deliberately public (listed in the version-
controlled allow-lists, each with a one-line justification).

Mutating routes (POST/PUT/PATCH/DELETE) are held to a stricter bar: they must
carry BOTH ``requires_auth`` and a ``required_permission`` marker, unless they
are in the tiny ``PUBLIC_MUTATION_ALLOWLIST`` (auth + webhooks + public forms).

This is the permanent, can't-forget answer to G1: a new CRUD route that ships
without a decorator and without a reviewed allow-list entry fails CI here.

S90 slice 4: the policy (allow-lists + offender classification) now lives in
**production** code at ``vbwd.security.route_audit`` so the ``flask
prod-readiness`` command reuses the exact same logic (DRY). This oracle layers
its assertions + negative fixture + stale-allowlist guard on top of that single
source of truth. Adding a public route is therefore a deliberate, reviewed diff
in ``vbwd/security/route_audit.py``, not a silent accident.
"""
import pytest
from flask import Blueprint, jsonify

from vbwd.plugins.base import PublicRouteDeclaration
from vbwd.security.route_audit import (
    PUBLIC_ALLOWLIST,
    PUBLIC_MUTATION_ALLOWLIST,
    RouteAudit,
    audit_routes,
    collect_public_routes,
    describe_offender,
    find_stale_allowlist_entries,
    find_unprotected_routes,
)


class _FakePlugin:
    """A minimal plugin that declares a fixed set of public routes.

    Used to exercise the collection mechanism without booting a real plugin —
    it honours exactly the ``declare_public_routes`` contract the audit relies
    on (Liskov: a test fake obeys the same contract as a production plugin).
    """

    def __init__(self, declaration: PublicRouteDeclaration):
        self._declaration = declaration

    def declare_public_routes(self) -> PublicRouteDeclaration:
        return self._declaration


class _FakePluginManager:
    """A stand-in ``PluginManager`` exposing only ``get_enabled_plugins``."""

    def __init__(self, plugins):
        self._plugins = plugins

    def get_enabled_plugins(self):
        return list(self._plugins)


def _build_app():
    """Boot the full app (core + enabled plugins) the unit suite uses."""
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    return create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": get_database_url(),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        }
    )


@pytest.fixture(scope="module")
def booted_app():
    """Boot the fully-loaded app once for the module."""
    return _build_app()


def test_every_route_is_protected_or_allowlisted(booted_app):
    """The keystone assertion: no unclassified exposure ships."""
    offenders = find_unprotected_routes(booted_app)
    assert not offenders, (
        "Route-exposure oracle found unprotected route(s). Each must either "
        "carry @require_auth (+ @require_permission for mutations) or be added "
        "to PUBLIC_ALLOWLIST / PUBLIC_MUTATION_ALLOWLIST with a justification:\n"
        + "\n".join(
            f"  - {describe_offender(route)}"
            for route in sorted(offenders, key=lambda route: route.path)
        )
    )


def test_allowlists_have_no_stale_entries(booted_app):
    """An allow-list entry that no longer matches a live rule must fail.

    Keeps the allow-lists from rotting: a removed/renamed public route forces
    a reviewed cleanup instead of lingering as a phantom exemption.
    """
    stale = find_stale_allowlist_entries(booted_app)
    assert not stale, (
        "Allow-listed route(s) not found in the live url_map (stale entry — "
        "remove or fix):\n" + "\n".join(f"  - {entry}" for entry in stale)
    )


def test_debug_routes_are_debug_gated_not_publicly_allowlisted(booted_app):
    """The /_routes + /_seed_status pair must be gated by @require_debug_enabled.

    Asserted via the marker, NOT via the public allow-list — they are hidden
    (404) in production rather than openly public.
    """
    debug_paths = {"/api/v1/_routes", "/api/v1/_seed_status"}
    by_path = {route.path: route for route in audit_routes(booted_app)}

    for path in debug_paths:
        assert path in by_path, f"Expected debug route {path} to be registered"
        route = by_path[path]
        assert route.requires_debug_enabled, (
            f"{path} must carry the requires_debug_enabled marker "
            "(@require_debug_enabled), so it is 404 in production."
        )
        assert path not in PUBLIC_ALLOWLIST, (
            f"{path} must NOT be in PUBLIC_ALLOWLIST — it is debug-gated, "
            "not openly public."
        )


def test_oracle_bites_on_an_unprotected_mutation():
    """Negative fixture: an unguarded POST route must be flagged by the guard.

    Registers a throwaway POST /api/v1/_oracle_probe on a fresh app and asserts
    the classifier names it — proving the guard actually catches a real gap.
    """
    app = _build_app()
    probe_bp = Blueprint("oracle_probe", __name__)

    @probe_bp.route("/api/v1/_oracle_probe", methods=["POST"])
    def _oracle_probe():  # pragma: no cover - never invoked, only introspected
        return jsonify({"ok": True})

    app.register_blueprint(probe_bp)

    offenders = find_unprotected_routes(app)
    assert any(route.path == "/api/v1/_oracle_probe" for route in offenders), (
        "Oracle failed to flag the deliberately-unprotected probe route — "
        "the guard does not bite."
    )


def test_route_audit_reports_structured_fields():
    """RouteAudit exposes the structured fields the readiness command reuses."""
    audit = RouteAudit(
        path="/api/v1/example",
        endpoint="example.handler",
        methods=["POST"],
        requires_auth=True,
        required_permission="example.manage",
        requires_admin=False,
        requires_debug_enabled=False,
    )
    assert audit.is_mutating is True
    assert audit.is_authorization_gated is True
    assert audit.methods_label == "POST"


def test_allowlists_are_exported_from_production_module():
    """The allow-lists are a production constant the readiness command shares."""
    assert isinstance(PUBLIC_ALLOWLIST, dict)
    assert isinstance(PUBLIC_MUTATION_ALLOWLIST, dict)
    # Every entry carries a non-empty justification string.
    assert all(bool(reason) for reason in PUBLIC_ALLOWLIST.values())
    assert all(bool(reason) for reason in PUBLIC_MUTATION_ALLOWLIST.values())


def test_route_namespace_groups_by_plugin_area():
    """The namespace helper isolates a route's owning plugin/area."""
    from vbwd.security.route_audit import _route_namespace

    assert _route_namespace("/api/v1/cms/embed-manifest") == "api/v1/cms"
    assert _route_namespace("/api/v1/cms/pages/<path:slug>") == "api/v1/cms"
    assert (
        _route_namespace("/api/v1/plugins/conekta/webhooks") == "api/v1/plugins/conekta"
    )


def test_stale_check_tolerates_unloaded_plugins_but_still_catches_rot():
    """A plugin-declared public route that no longer matches a live rule in a
    LOADED namespace is genuinely stale and flagged; an entry whose namespace is
    entirely absent belongs to an unloaded plugin and is skipped (configuration,
    not rot). The declared routes come from the enabled plugins via the seam, so
    this holds for both core and plugin allow-list entries.
    """
    from flask import Flask

    app = Flask(__name__)
    live_bp = Blueprint("widget_namespace_probe", __name__)

    @live_bp.route("/api/v1/widget/present", methods=["GET"])
    def _widget_present():  # pragma: no cover - introspected only
        return jsonify({"ok": True})

    app.register_blueprint(live_bp)

    # A fake plugin declares one present + one absent route in the LOADED
    # ``api/v1/widget`` namespace, plus one route in an entirely-absent namespace.
    fake_plugin = _FakePlugin(
        PublicRouteDeclaration(
            read={
                "/api/v1/widget/present": "Present sibling keeps the namespace live.",
                "/api/v1/widget/absent": "Removed public route in a loaded namespace.",
                "/api/v1/unloaded/thing": "Belongs to a plugin not loaded in this boot.",
            }
        )
    )
    app.plugin_manager = _FakePluginManager([fake_plugin])  # type: ignore[attr-defined]

    stale = find_stale_allowlist_entries(app)

    # A loaded namespace missing a specific declared route → flagged (rot).
    assert "PUBLIC_ALLOWLIST: /api/v1/widget/absent" in stale
    # An entirely-unloaded namespace's entry → skipped, not reported as rot.
    assert not any("unloaded" in entry for entry in stale)


def test_collect_public_routes_unions_core_and_plugin_declarations():
    """The collection mechanism unions core's own lists with plugin declarations.

    Core owns only its genuinely-core public routes; each plugin contributes its
    own via ``declare_public_routes()``. An uncloned/disabled plugin simply does
    not appear in ``get_enabled_plugins()`` and so contributes nothing.
    """
    from flask import Flask

    app = Flask(__name__)
    fake_plugin = _FakePlugin(
        PublicRouteDeclaration(
            read={"/api/v1/demo/catalog": "Public demo catalog."},
            mutation={"/api/v1/demo/hook": "Signature-gated demo webhook."},
        )
    )
    app.plugin_manager = _FakePluginManager([fake_plugin])  # type: ignore[attr-defined]

    read_allowlist, mutation_allowlist = collect_public_routes(app)

    # Core entries are still present (the union starts from core's own lists).
    assert "/api/v1/config" in read_allowlist
    assert "/api/v1/auth/login" in mutation_allowlist
    # The plugin's declared routes are merged in.
    assert read_allowlist["/api/v1/demo/catalog"] == "Public demo catalog."
    assert mutation_allowlist["/api/v1/demo/hook"] == "Signature-gated demo webhook."


def test_core_allowlists_contain_no_plugin_route(booted_app):
    """Guard: core's own allow-lists name ZERO plugin routes (agnosticism).

    After the inversion, every plugin-specific public route is declared by its
    owning plugin via ``declare_public_routes()``; core keeps only genuinely-core
    public routes. This asserts each entry still hard-coded in
    ``PUBLIC_ALLOWLIST`` / ``PUBLIC_MUTATION_ALLOWLIST`` is served by a CORE
    blueprint — never by a plugin's blueprint.
    """
    plugin_blueprint_names = set()
    for plugin in booted_app.plugin_manager.get_enabled_plugins():
        for getter in ("get_blueprint", "get_admin_blueprint"):
            blueprint = getattr(plugin, getter)()
            if blueprint is not None:
                plugin_blueprint_names.add(blueprint.name)

    endpoint_by_path = {
        str(rule): rule.endpoint for rule in booted_app.url_map.iter_rules()
    }

    offenders = []
    for path in list(PUBLIC_ALLOWLIST) + list(PUBLIC_MUTATION_ALLOWLIST):
        endpoint = endpoint_by_path.get(path)
        if endpoint is None:
            continue  # a core route not registered in this boot's set
        blueprint_name = endpoint.rsplit(".", 1)[0] if "." in endpoint else None
        if blueprint_name in plugin_blueprint_names:
            offenders.append(f"{path} → plugin blueprint {blueprint_name!r}")

    assert not offenders, (
        "Core allow-lists must name NO plugin route (core stays agnostic). Move "
        "each of these into the owning plugin's declare_public_routes():\n  - "
        + "\n  - ".join(offenders)
    )
