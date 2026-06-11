"""S52.3 — core ``require_api_key`` guard specs (Flask test client + fake service).

Liskov: on success the guard sets ``g.user_id`` AND ``g.user`` exactly like
``require_auth`` so ``require_permission`` and downstream handlers are
auth-mechanism-agnostic. The token is never logged; IP whitelist is enforced
before scope.
"""
from types import SimpleNamespace

import pytest
from flask import Flask, g, jsonify

import vbwd.middleware.api_key_auth as api_key_auth
from vbwd.middleware.api_key_auth import require_api_key


class _FakeService:
    """Minimal ApiKeyService double honouring the real method contract."""

    def __init__(self, key=None):
        self._key = key
        self.touched = []

    def verify(self, plaintext):
        return self._key

    def is_ip_allowed(self, key, client_ip):
        whitelist = key.ip_whitelist or []
        return not whitelist or client_ip in whitelist

    def has_scope(self, key, required_scope):
        return required_scope in (key.scopes or [])

    def touch(self, key):
        self.touched.append(key)


def _key(user_id="user-1", scopes=None, ip_whitelist=None):
    return SimpleNamespace(
        user_id=user_id,
        scopes=scopes or [],
        ip_whitelist=ip_whitelist or [],
        is_active=True,
    )


@pytest.fixture
def gated_app(monkeypatch):
    """Flask app with one ``require_api_key('demo:scope')`` route + a swappable
    fake service + a fake user loader."""
    app = Flask(__name__)
    app.config["TESTING"] = True

    state = {"service": _FakeService(None), "user": object()}

    monkeypatch.setattr(
        api_key_auth, "_resolve_api_key_service", lambda: state["service"]
    )
    monkeypatch.setattr(api_key_auth, "_load_user", lambda user_id: state["user"])

    @app.route("/protected")
    @require_api_key("demo:scope")
    def protected_route():
        return jsonify(
            {
                "user_id": g.user_id,
                "user_loaded": g.user is state["user"],
            }
        )

    app.config["_GUARD_STATE"] = state
    return app


def test_missing_header_returns_401(gated_app):
    response = gated_app.test_client().get("/protected")
    assert response.status_code == 401


def test_blank_header_returns_401(gated_app):
    response = gated_app.test_client().get("/protected", headers={"X-API-Key": ""})
    assert response.status_code == 401


def test_unknown_or_inactive_key_returns_401(gated_app):
    # service.verify returns None for unknown/inactive
    response = gated_app.test_client().get(
        "/protected", headers={"X-API-Key": "vbwdk_unknown"}
    )
    assert response.status_code == 401


def test_ip_not_whitelisted_returns_403(gated_app):
    state = gated_app.config["_GUARD_STATE"]
    state["service"] = _FakeService(
        _key(scopes=["demo:scope"], ip_whitelist=["10.0.0.1"])
    )
    response = gated_app.test_client().get(
        "/protected", headers={"X-API-Key": "vbwdk_ok"}
    )
    assert response.status_code == 403


def test_scope_missing_returns_403(gated_app):
    state = gated_app.config["_GUARD_STATE"]
    state["service"] = _FakeService(_key(scopes=["other:scope"]))
    response = gated_app.test_client().get(
        "/protected", headers={"X-API-Key": "vbwdk_ok"}
    )
    assert response.status_code == 403


def test_success_sets_g_user_id_and_g_user_and_touches(gated_app):
    state = gated_app.config["_GUARD_STATE"]
    service = _FakeService(_key(user_id="user-1", scopes=["demo:scope"]))
    state["service"] = service
    response = gated_app.test_client().get(
        "/protected", headers={"X-API-Key": "vbwdk_ok"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["user_id"] == "user-1"
    assert body["user_loaded"] is True
    assert len(service.touched) == 1


def test_guard_marks_requires_auth_for_route_catalogue():
    wrapped = require_api_key("x")(lambda: None)
    assert getattr(wrapped, "requires_auth", False) is True


def test_no_scope_allows_any_valid_key_and_exposes_g_api_key(monkeypatch):
    """``require_api_key()`` (no scope) passes any valid, active, IP-allowed key
    — the health/test endpoint — even with an EMPTY scope list, and sets
    ``g.api_key`` so the handler can echo the key's identity."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    key = _key(user_id="user-9", scopes=[])  # deliberately no scopes
    service = _FakeService(key)
    monkeypatch.setattr(api_key_auth, "_resolve_api_key_service", lambda: service)
    monkeypatch.setattr(api_key_auth, "_load_user", lambda user_id: object())

    @app.route("/health")
    @require_api_key()
    def health():
        return jsonify({"user_id": g.user_id, "has_key": g.api_key is key})

    response = app.test_client().get("/health", headers={"X-API-Key": "vbwdk_ok"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["user_id"] == "user-9"
    assert body["has_key"] is True
    assert len(service.touched) == 1


def test_no_scope_still_requires_a_valid_key(monkeypatch):
    """No scope does NOT mean no auth: missing/invalid key is still 401."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    monkeypatch.setattr(
        api_key_auth, "_resolve_api_key_service", lambda: _FakeService(None)
    )

    @app.route("/health")
    @require_api_key()
    def health():
        return jsonify({"ok": True})

    client = app.test_client()
    assert client.get("/health").status_code == 401  # no header
    assert (
        client.get("/health", headers={"X-API-Key": "vbwdk_bad"}).status_code == 401
    )  # unknown/inactive
