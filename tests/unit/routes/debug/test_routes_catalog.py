"""Specs for ``GET /api/v1/_routes`` — the route-catalog introspection
endpoint (S30 slice 1). Debug-gated; lists every registered route with its
method, path template, endpoint, and auth requirement so the load-test
harness can fail fast on URL drift.
"""


def test_returns_404_when_debug_disabled(app):
    """Spec 1: with ENABLE_DEBUG_ENDPOINTS False, the endpoint is hidden (404)."""
    app.config["ENABLE_DEBUG_ENDPOINTS"] = False
    client = app.test_client()
    response = client.get("/api/v1/_routes")
    assert response.status_code == 404


def test_lists_routes_when_debug_enabled(app):
    """Spec 2: with the flag on, returns a list containing the app's routes."""
    app.config["ENABLE_DEBUG_ENDPOINTS"] = True
    client = app.test_client()
    response = client.get("/api/v1/_routes")
    assert response.status_code == 200
    payload = response.get_json()
    assert "routes" in payload
    assert isinstance(payload["routes"], list)
    assert len(payload["routes"]) > 0
    paths = {entry["path"] for entry in payload["routes"]}
    assert "/api/v1/health" in paths


def test_each_entry_has_contract_fields(app):
    """Spec 3: every entry exposes method, path, endpoint, auth_required,
    permission keys (the harness contract)."""
    app.config["ENABLE_DEBUG_ENDPOINTS"] = True
    client = app.test_client()
    response = client.get("/api/v1/_routes")
    payload = response.get_json()
    for entry in payload["routes"]:
        assert set(entry.keys()) == {
            "method",
            "path",
            "endpoint",
            "auth_required",
            "permission",
        }
        assert isinstance(entry["method"], str)
        assert isinstance(entry["path"], str)
        assert isinstance(entry["auth_required"], bool)


def test_methods_exclude_head_and_options(app):
    """Spec 4: implicit HEAD/OPTIONS methods are not listed as separate rows."""
    app.config["ENABLE_DEBUG_ENDPOINTS"] = True
    client = app.test_client()
    response = client.get("/api/v1/_routes")
    payload = response.get_json()
    methods = {entry["method"] for entry in payload["routes"]}
    assert "HEAD" not in methods
    assert "OPTIONS" not in methods


def test_auth_required_true_for_protected_route(app):
    """Spec 5: a route decorated with @require_auth reports auth_required=True;
    an unauthenticated route (health) reports False."""
    app.config["ENABLE_DEBUG_ENDPOINTS"] = True
    client = app.test_client()
    response = client.get("/api/v1/_routes")
    by_path = {}
    for entry in response.get_json()["routes"]:
        by_path.setdefault(entry["path"], entry)

    # /api/v1/health is unauthenticated.
    assert by_path["/api/v1/health"]["auth_required"] is False

    # /api/v1/user/profile is decorated with @require_auth.
    profile = next(
        entry
        for entry in response.get_json()["routes"]
        if entry["path"] == "/api/v1/user/profile" and entry["method"] == "GET"
    )
    assert profile["auth_required"] is True


def test_plugin_routes_appear(app):
    """Spec 6: routes registered by enabled plugins appear in the catalog."""
    app.config["ENABLE_DEBUG_ENDPOINTS"] = True
    client = app.test_client()
    response = client.get("/api/v1/_routes")
    endpoints = {entry["endpoint"] for entry in response.get_json()["routes"]}
    # The debug blueprint itself is registered and must appear.
    assert any(endpoint.startswith("debug.") for endpoint in endpoints)
