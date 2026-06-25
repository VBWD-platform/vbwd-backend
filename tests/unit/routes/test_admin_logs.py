"""S106.1 / S106.2 — admin log-read routes (centralized log management).

Covers the contract for ``/api/v1/admin/logs*``:
  * every endpoint is gated by ``@require_auth`` + ``@require_permission(logs.read)``
    — 401 unauthenticated, 403 without the permission;
  * ``/scopes`` lists the discovered scopes + streams;
  * ``GET /logs`` returns merged, newest-first records with the query filters;
  * ``/download`` streams a single scope/stream as ndjson;
  * an unknown / traversal scope is a 400 (the reader's ValueError), never a path
    escape;
  * ``/stream`` is an ``text/event-stream`` and is permission-gated too.

The routes build a ``LocalFilesystemManager`` bound to ``VBWD_VAR_DIR`` per
request (like ``core_settings_store``), so each test points that env at a
throwaway dir and writes JSON-line fixtures there.
"""
import json
from unittest.mock import patch
from uuid import uuid4

import pytest

from tests.fixtures.access import (
    make_user_no_permissions,
    make_user_with_permissions,
)

BASE = "/api/v1/admin/logs"


@pytest.fixture
def logs_root(tmp_path, monkeypatch):
    var_root = tmp_path / "var"
    (var_root / "logs" / "core").mkdir(parents=True)
    (var_root / "logs" / "shop").mkdir(parents=True)
    monkeypatch.setenv("VBWD_VAR_DIR", str(var_root))
    return var_root


def _seed(logs_root, relative, records):
    target = logs_root / "logs" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _rec(ts, level, scope, msg):
    return {
        "ts": ts,
        "level": level,
        "scope": scope,
        "stream": "error" if level == "ERROR" else "info",
        "logger": f"{scope}.x",
        "msg": msg,
    }


def _mock_auth(mock_repo_cls, mock_auth_cls, user):
    mock_repo_cls.return_value.find_by_id.return_value = user
    mock_auth_cls.return_value.verify_token.return_value = str(uuid4())


def _headers():
    return {"Authorization": "Bearer valid"}


# --------------------------------------------------------------------------
# Auth gating
# --------------------------------------------------------------------------


def test_logs_unauthenticated(client, logs_root):
    assert client.get(BASE).status_code == 401


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_logs_forbidden_without_permission(mock_repo, mock_auth, client, logs_root):
    _mock_auth(mock_repo, mock_auth, make_user_no_permissions())
    assert client.get(BASE, headers=_headers()).status_code == 403


# --------------------------------------------------------------------------
# /scopes + query
# --------------------------------------------------------------------------


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_scopes_lists_discovered(mock_repo, mock_auth, client, logs_root):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("logs.read"))
    _seed(logs_root, "core/error.log", [_rec(1.0, "ERROR", "core", "x")])
    _seed(logs_root, "shop/error.log", [_rec(2.0, "ERROR", "shop", "y")])

    response = client.get(f"{BASE}/scopes", headers=_headers())
    assert response.status_code == 200
    body = response.get_json()
    assert set(body["scopes"]) == {"core", "shop"}
    assert "error" in body["streams"]


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_query_returns_merged_newest_first(mock_repo, mock_auth, client, logs_root):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("logs.read"))
    _seed(logs_root, "core/error.log", [_rec(10.0, "ERROR", "core", "old")])
    _seed(logs_root, "shop/error.log", [_rec(20.0, "ERROR", "shop", "new")])

    response = client.get(f"{BASE}?since=0", headers=_headers())
    assert response.status_code == 200
    body = response.get_json()
    assert [r["msg"] for r in body["records"]] == ["new", "old"]
    assert "truncated" in body


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_query_filters_scope_and_level(mock_repo, mock_auth, client, logs_root):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("logs.read"))
    _seed(logs_root, "core/info.log", [_rec(1.0, "INFO", "core", "info")])
    _seed(logs_root, "core/error.log", [_rec(2.0, "ERROR", "core", "err")])
    _seed(logs_root, "shop/error.log", [_rec(3.0, "ERROR", "shop", "shop-err")])

    response = client.get(f"{BASE}?since=0&scope=core&level=error", headers=_headers())
    body = response.get_json()
    assert [r["msg"] for r in body["records"]] == ["err"]


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_query_unknown_scope_is_400(mock_repo, mock_auth, client, logs_root):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("logs.read"))
    _seed(logs_root, "core/error.log", [_rec(1.0, "ERROR", "core", "x")])

    response = client.get(f"{BASE}?since=0&scope=../etc", headers=_headers())
    assert response.status_code == 400


# --------------------------------------------------------------------------
# /download
# --------------------------------------------------------------------------


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_download_returns_ndjson(mock_repo, mock_auth, client, logs_root):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("logs.read"))
    _seed(logs_root, "core/error.log", [_rec(1.0, "ERROR", "core", "a")])

    response = client.get(
        f"{BASE}/download?scope=core&stream=error", headers=_headers()
    )
    assert response.status_code == 200
    assert response.mimetype == "application/x-ndjson"
    assert b'"msg": "a"' in response.data or b'"msg":"a"' in response.data


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_download_requires_scope_and_stream(mock_repo, mock_auth, client, logs_root):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("logs.read"))
    response = client.get(f"{BASE}/download?scope=core", headers=_headers())
    assert response.status_code == 400


# --------------------------------------------------------------------------
# /stream (SSE)
# --------------------------------------------------------------------------


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_stream_is_event_stream(mock_repo, mock_auth, client, logs_root):
    _mock_auth(mock_repo, mock_auth, make_user_with_permissions("logs.read"))
    _seed(logs_root, "core/error.log", [_rec(1.0, "ERROR", "core", "tailme")])

    response = client.get(f"{BASE}/stream?scope=core&stream=error", headers=_headers())
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    # X-Accel-Buffering disables nginx buffering so the tail flushes live.
    assert response.headers.get("X-Accel-Buffering") == "no"
    body = response.get_data(as_text=True)
    assert "tailme" in body


def test_stream_unauthenticated(client, logs_root):
    assert client.get(f"{BASE}/stream?scope=core&stream=error").status_code == 401
