"""S152 C2 — ``InternalApiClient``: in-process dispatch to the app's own API.

Every test builds a real app through ``create_app`` (ProxyFix ON, the deployed
two-hop topology) and mounts a test-only blueprint on it. Nothing here is
registered in production code.
"""
import socket

import pytest
from flask import Blueprint, g, jsonify, request

from vbwd.plugins.payment_route_helpers import resolve_frontend_base
from vbwd.services.internal_api import (
    InternalApiClient,
    InternalApiRecursionError,
    InternalResponse,
    resolve_internal_api_client,
)

ECHO_PATH = "/api/v1/test-internal-api/echo"
LIMITED_PATH = "/api/v1/test-internal-api/limited"
NESTED_PATH = "/api/v1/test-internal-api/nested"
PAYMENT_BASE_PATH = "/api/v1/test-internal-api/payment-base"
OUTER_PATH = "/test-internal-api/outer"
INNER_RATE_LIMIT = "2 per minute"
INNER_CALLS_OVER_LIMIT = 3
HTTP_OK = 200
HTTP_TOO_MANY_REQUESTS = 429

BROWSER_CLIENT_IP = "203.0.113.7"
FIRST_PROXY_IP = "10.0.0.2"
APP_NGINX_IP = "10.0.0.3"
PUBLIC_HOST = "shop.example.com"
BROWSER_ORIGIN = "https://shop.example.com"

PROXIED_HEADERS = {
    # Two trusted hops append to X-Forwarded-For: the browser, then the outer
    # proxy; the app-container nginx is REMOTE_ADDR.
    "X-Forwarded-For": f"{BROWSER_CLIENT_IP}, {FIRST_PROXY_IP}",
    "X-Forwarded-Proto": "https",
    "X-Forwarded-Host": PUBLIC_HOST,
}


def _build_test_app(rate_limit_enabled: bool):
    from vbwd.app import create_app
    from vbwd.config import get_database_url
    from vbwd.extensions import csrf, limiter

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": get_database_url(),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "RATELIMIT_ENABLED": rate_limit_enabled,
            "RATELIMIT_STORAGE_URL": "memory://",
            "PROXY_FIX_ENABLED": True,
        }
    )
    test_blueprint = _build_test_blueprint(limiter)
    # Mirrors every API blueprint in create_app: JWT-authenticated, CSRF-exempt.
    csrf.exempt(test_blueprint)
    app.register_blueprint(test_blueprint)
    if rate_limit_enabled:
        limiter.reset()
    return app


def _build_test_blueprint(limiter) -> Blueprint:
    blueprint = Blueprint("test_internal_api", __name__)

    @blueprint.route(ECHO_PATH, methods=["GET", "POST", "PUT", "DELETE"])
    def echo():
        return jsonify(
            {
                "method": request.method,
                "remote_addr": request.remote_addr,
                "host": request.host,
                "scheme": request.scheme,
                "headers": dict(request.headers),
                "cookies": dict(request.cookies),
                "query": request.args.to_dict(),
                "json": request.get_json(silent=True),
                "g_marker": getattr(g, "test_marker", None),
            }
        )

    @blueprint.route(LIMITED_PATH)
    @limiter.limit(INNER_RATE_LIMIT)
    def limited():
        return jsonify({"ok": True})

    @blueprint.route(NESTED_PATH)
    def nested():
        try:
            resolve_internal_api_client().get(ECHO_PATH, forward_from=request)
        except InternalApiRecursionError:
            return jsonify({"refused": True})
        return jsonify({"refused": False})

    @blueprint.route(PAYMENT_BASE_PATH)
    def payment_base():
        return jsonify({"frontend_base": resolve_frontend_base(request)})

    @blueprint.route(OUTER_PATH, methods=["GET", "POST"])
    def outer():
        target_path = request.args.get("target", ECHO_PATH)
        repeat = int(request.args.get("repeat", "1"))
        g.test_marker = "outer"
        responses = [
            resolve_internal_api_client().get(target_path, forward_from=request)
            for _ in range(repeat)
        ]
        return jsonify(
            {
                "statuses": [response.status for response in responses],
                "inner": responses[-1].json(),
                "outer_remote_addr": request.remote_addr,
                "outer_host": request.host,
                "outer_scheme": request.scheme,
            }
        )

    return blueprint


@pytest.fixture
def app():
    return _build_test_app(rate_limit_enabled=False)


@pytest.fixture
def rate_limited_app():
    return _build_test_app(rate_limit_enabled=True)


def _proxied_outer_get(app, query_string=None, headers=None):
    combined_headers = dict(PROXIED_HEADERS)
    combined_headers.update(headers or {})
    return app.test_client().get(
        OUTER_PATH,
        query_string=query_string or {},
        headers=combined_headers,
        environ_base={"REMOTE_ADDR": APP_NGINX_IP},
    )


class TestRegistration:
    def test_client_is_registered_and_resolvable(self, app):
        with app.app_context():
            assert isinstance(resolve_internal_api_client(), InternalApiClient)
            assert resolve_internal_api_client() is app.extensions["internal_api"]


class TestPathGuard:
    @pytest.mark.parametrize(
        "path",
        [
            "/_render/home",
            "/admin/index.html",
            "/uploads/a.png",
            "/api/v2/x",
            "api/v1/x",
        ],
    )
    def test_refuses_non_api_paths(self, app, path):
        client = app.extensions["internal_api"]
        with pytest.raises(ValueError):
            client.get(path)


class TestHeaderForwarding:
    def test_forwards_only_allow_listed_headers_and_cookies(self, app):
        outer_client = app.test_client()
        outer_client.set_cookie("vbwd_lang", "de")
        outer_client.set_cookie("session_secret", "do-not-forward")
        response = outer_client.get(
            OUTER_PATH,
            headers={
                "Authorization": "Bearer outer-token",
                "Accept-Language": "de-DE",
                "Origin": BROWSER_ORIGIN,
                "Referer": f"{BROWSER_ORIGIN}/checkout",
                "User-Agent": "BrowserAgent/1.0",
                "X-Request-ID": "req-123",
                "X-Custom-Secret": "do-not-forward",
                "X-Api-Key": "do-not-forward",
            },
        )

        inner = response.get_json()["inner"]
        inner_headers = inner["headers"]
        assert inner_headers["Authorization"] == "Bearer outer-token"
        assert inner_headers["Accept-Language"] == "de-DE"
        assert inner_headers["Origin"] == BROWSER_ORIGIN
        assert inner_headers["Referer"] == f"{BROWSER_ORIGIN}/checkout"
        assert inner_headers["User-Agent"] == "BrowserAgent/1.0"
        assert inner_headers["X-Request-Id"] == "req-123"
        assert "X-Custom-Secret" not in inner_headers
        assert "X-Api-Key" not in inner_headers
        assert inner["cookies"] == {"vbwd_lang": "de"}

    def test_cookie_allow_list_is_configurable(self, app):
        client = InternalApiClient(app, forwarded_cookie_names={"other_cookie"})
        with app.test_request_context(
            "/", headers={"Cookie": "vbwd_lang=de; other_cookie=yes"}
        ):
            response = client.get(ECHO_PATH, forward_from=request)

        assert response.json()["cookies"] == {"other_cookie": "yes"}

    def test_explicit_headers_merge_on_top_of_forwarded(self, app):
        client = app.extensions["internal_api"]
        with app.test_request_context(
            "/", headers={"Authorization": "Bearer outer", "Accept-Language": "en"}
        ):
            response = client.get(
                ECHO_PATH,
                forward_from=request,
                headers={"Authorization": "Bearer explicit"},
            )

        inner_headers = response.json()["headers"]
        assert inner_headers["Authorization"] == "Bearer explicit"
        assert inner_headers["Accept-Language"] == "en"


class TestProxyFix:
    def test_client_ip_host_and_scheme_survive_proxyfix(self, app):
        body = _proxied_outer_get(app).get_json()

        assert body["outer_remote_addr"] == BROWSER_CLIENT_IP
        inner = body["inner"]
        assert inner["remote_addr"] == body["outer_remote_addr"]
        assert inner["host"] == body["outer_host"] == PUBLIC_HOST
        assert inner["scheme"] == body["outer_scheme"] == "https"

    def test_direct_connection_values_survive_without_forwarded_headers(self, app):
        body = (
            app.test_client()
            .get(OUTER_PATH, environ_base={"REMOTE_ADDR": BROWSER_CLIENT_IP})
            .get_json()
        )

        inner = body["inner"]
        assert inner["remote_addr"] == body["outer_remote_addr"] == BROWSER_CLIENT_IP
        assert inner["host"] == body["outer_host"]
        assert inner["scheme"] == body["outer_scheme"]
        assert "X-Forwarded-For" not in inner["headers"]

    def test_forwarded_headers_are_not_stacked_twice(self, app):
        inner_headers = _proxied_outer_get(app).get_json()["inner"]["headers"]

        assert inner_headers["X-Forwarded-For"] == PROXIED_HEADERS["X-Forwarded-For"]
        assert inner_headers["X-Forwarded-Proto"] == "https"
        assert inner_headers["X-Forwarded-Host"] == PUBLIC_HOST

    def test_payment_style_origin_resolution_uses_browser_origin(self, app):
        body = _proxied_outer_get(
            app,
            query_string={"target": PAYMENT_BASE_PATH},
            headers={"Origin": BROWSER_ORIGIN},
        ).get_json()

        assert body["inner"]["frontend_base"] == BROWSER_ORIGIN

    def test_payment_style_origin_falls_back_to_public_host(self, app):
        body = _proxied_outer_get(
            app, query_string={"target": PAYMENT_BASE_PATH}
        ).get_json()

        assert body["inner"]["frontend_base"] == f"https://{PUBLIC_HOST}"


class TestRecursionGuard:
    def test_recursion_guard(self, app):
        body = _proxied_outer_get(app, query_string={"target": NESTED_PATH}).get_json()

        assert body["statuses"] == [HTTP_OK]
        assert body["inner"] == {"refused": True}

    def test_dispatch_inside_inner_environ_raises(self, app):
        client = app.extensions["internal_api"]
        with app.test_request_context(
            ECHO_PATH, environ_base={"vbwd.internal_depth": 1}
        ):
            with pytest.raises(InternalApiRecursionError):
                client.get(ECHO_PATH)


class TestRateLimits:
    def test_inner_calls_are_rate_limited_on_real_client(self, rate_limited_app):
        body = _proxied_outer_get(
            rate_limited_app,
            query_string={"target": LIMITED_PATH, "repeat": INNER_CALLS_OVER_LIMIT},
        ).get_json()

        assert body["statuses"] == [HTTP_OK, HTTP_OK, HTTP_TOO_MANY_REQUESTS]


class TestDispatch:
    def test_no_network_io(self, app, monkeypatch):
        attempted_network_calls = []

        def refuse_network(*arguments, **keyword_arguments):
            attempted_network_calls.append(arguments)
            raise AssertionError("InternalApiClient must not open network IO")

        monkeypatch.setattr(socket.socket, "connect", refuse_network)
        monkeypatch.setattr(socket.socket, "connect_ex", refuse_network)
        monkeypatch.setattr(socket, "create_connection", refuse_network)

        response = app.extensions["internal_api"].post(
            ECHO_PATH, json={"item": 1}, query={"page": "2"}
        )

        assert attempted_network_calls == []
        assert response.status == HTTP_OK
        assert response.json()["json"] == {"item": 1}
        assert response.json()["query"] == {"page": "2"}

    def test_inner_request_does_not_share_outer_g(self, app):
        body = _proxied_outer_get(app).get_json()

        assert body["inner"]["g_marker"] is None

    def test_works_outside_request_with_explicit_headers(self, app):
        response = app.extensions["internal_api"].get(
            ECHO_PATH, headers={"Authorization": "Bearer worker-token"}
        )

        assert response.status == HTTP_OK
        assert response.json()["headers"]["Authorization"] == "Bearer worker-token"

    def test_request_id_propagated(self, app):
        body = _proxied_outer_get(
            app, headers={"X-Request-ID": "correlation-42"}
        ).get_json()

        assert body["inner"]["headers"]["X-Request-Id"] == "correlation-42"

    @pytest.mark.parametrize("method_name", ["get", "post", "put", "delete"])
    def test_verb_wrappers_dispatch_their_method(self, app, method_name):
        client = app.extensions["internal_api"]
        response = getattr(client, method_name)(ECHO_PATH)
        assert response.json()["method"] == method_name.upper()

    def test_response_is_frozen_with_status_headers_and_text(self, app):
        response = app.extensions["internal_api"].get("/api/v1/health")

        assert isinstance(response, InternalResponse)
        assert response.status == HTTP_OK
        assert response.headers["Content-Type"].startswith("application/json")
        assert '"status"' in response.text
        with pytest.raises(AttributeError):
            setattr(response, "status", 500)
