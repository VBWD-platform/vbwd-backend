"""S14 — ``/api/v1/ready`` does a real DB probe; ``/api/v1/health``
stays cheap (process-alive only).

Liveness and readiness are distinct: a stuck DB connection should not
restart the container (liveness=ok), but the load balancer must stop
routing to it (readiness=fail). Redis probe deferred — no dedicated
redis client wrapper exists in `vbwd/extensions.py` today; adding one
is out of scope for S14 (logged in the sprint Outcome).
"""
from unittest.mock import patch


def test_health_returns_200_always(client):
    """``/health`` is cheap process-alive probe; no I/O."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"


def test_ready_returns_200_when_db_ok(client):
    """Happy path: DB probe succeeds, body shows per-component status."""
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.get_json()
    assert body["db"] is True


def test_ready_returns_503_when_db_unreachable(client):
    """DB probe failure → 503, body shows which probe failed."""
    from vbwd.extensions import db

    with patch.object(db.session, "execute", side_effect=Exception("DB down")):
        response = client.get("/api/v1/ready")
    assert response.status_code == 503
    body = response.get_json()
    assert body["db"] is False
    assert "error" in body
