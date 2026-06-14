"""S66 — ApnsClient unit specs (httpx mocked via an injected MockTransport).

The client is pure transport (Liskov): it surfaces per-token results —
including 410 for a stale token — and NEVER mutates device-token rows.
Revocation is the caller's (the plugin hook's) responsibility.
"""
import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from vbwd.services.apns_client import ApnsClient

TEST_KEY_ID = "TESTKEY123"
TEST_TEAM_ID = "TESTTEAM12"
TEST_BUNDLE_ID = "com.vbwd.app"


@pytest.fixture
def signing_key_path(tmp_path):
    """A real ES256 (P-256) private key written as a .p8 PEM file."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "apns_key.p8"
    key_file.write_bytes(pem_bytes)
    return str(key_file)


def _client(signing_key_path, transport, use_sandbox=False):
    return ApnsClient(
        key_path=signing_key_path,
        key_id=TEST_KEY_ID,
        team_id=TEST_TEAM_ID,
        bundle_id=TEST_BUNDLE_ID,
        use_sandbox=use_sandbox,
        transport=transport,
    )


def _recording_transport(captured_requests, status_code=200, body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(status_code, json=body if body is not None else {})

    return httpx.MockTransport(handler)


def test_send_success_returns_per_token_result(signing_key_path):
    captured_requests: list = []
    transport = _recording_transport(captured_requests, status_code=200)
    client = _client(signing_key_path, transport)

    results = client.send_bulk(["token-a", "token-b"], {"aps": {"badge": 1}})

    assert len(results) == 2
    assert all(result.success for result in results)
    assert [result.token for result in results] == ["token-a", "token-b"]
    assert all(result.status == 200 for result in results)
    # One POST per token, addressed to /3/device/<token>.
    assert len(captured_requests) == 2
    assert captured_requests[0].url.path == "/3/device/token-a"
    assert captured_requests[1].url.path == "/3/device/token-b"
    assert captured_requests[0].headers["apns-topic"] == TEST_BUNDLE_ID
    assert captured_requests[0].headers["apns-push-type"] == "alert"
    assert json.loads(captured_requests[0].content) == {"aps": {"badge": 1}}


def test_send_bad_token_surfaces_410_without_revoking(signing_key_path):
    """The 410 is surfaced in the result; the client is transport-only and
    performs no revocation — the caller (the plugin hook) decides."""
    captured_requests: list = []
    transport = _recording_transport(
        captured_requests, status_code=410, body={"reason": "Unregistered"}
    )
    client = _client(signing_key_path, transport)

    results = client.send_bulk(["stale-token"], {"aps": {}})

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].status == 410
    assert results[0].reason == "Unregistered"


def test_send_uses_sandbox_endpoint_when_flag_set(signing_key_path):
    captured_requests: list = []
    transport = _recording_transport(captured_requests)
    client = _client(signing_key_path, transport, use_sandbox=True)

    client.send_bulk(["token-a"], {"aps": {}})

    assert captured_requests[0].url.host == "api.sandbox.push.apple.com"


def test_send_uses_production_endpoint_by_default(signing_key_path):
    captured_requests: list = []
    transport = _recording_transport(captured_requests)
    client = _client(signing_key_path, transport, use_sandbox=False)

    client.send_bulk(["token-a"], {"aps": {}})

    assert captured_requests[0].url.host == "api.push.apple.com"


def test_jwt_payload_has_required_claims(signing_key_path):
    captured_requests: list = []
    transport = _recording_transport(captured_requests)
    client = _client(signing_key_path, transport)

    client.send_bulk(["token-a"], {"aps": {}})

    authorization = captured_requests[0].headers["authorization"]
    assert authorization.startswith("bearer ")
    provider_token = authorization[len("bearer ") :]
    header = jwt.get_unverified_header(provider_token)
    assert header["kid"] == TEST_KEY_ID
    assert header["alg"] == "ES256"
    claims = jwt.decode(provider_token, options={"verify_signature": False})
    assert claims["iss"] == TEST_TEAM_ID
    assert isinstance(claims["iat"], int)


def test_missing_key_makes_send_bulk_a_graceful_noop(tmp_path):
    client = ApnsClient(
        key_path=str(tmp_path / "does_not_exist.p8"),
        key_id=TEST_KEY_ID,
        team_id=TEST_TEAM_ID,
        bundle_id=TEST_BUNDLE_ID,
    )

    assert client.enabled is False
    assert client.send_bulk(["token-a"], {"aps": {}}) == []


def test_unset_key_path_makes_send_bulk_a_graceful_noop():
    client = ApnsClient(
        key_path=None,
        key_id=TEST_KEY_ID,
        team_id=TEST_TEAM_ID,
        bundle_id=TEST_BUNDLE_ID,
    )

    assert client.enabled is False
    assert client.send_bulk(["token-a"], {"aps": {}}) == []


def test_send_bulk_alert_default_uses_apns_push_type_alert_and_priority_10(
    signing_key_path,
):
    """S68 — the default (S66 alert) path is byte-identical: push-type alert,
    priority 10. Existing callers pass no kwargs and keep working."""
    captured_requests: list = []
    transport = _recording_transport(captured_requests)
    client = _client(signing_key_path, transport)

    client.send_bulk(["token-a"], {"aps": {"badge": 1}})

    assert captured_requests[0].headers["apns-push-type"] == "alert"
    assert captured_requests[0].headers["apns-priority"] == "10"


def test_send_bulk_background_uses_apns_push_type_background_and_priority_5(
    signing_key_path,
):
    """S68 — a silent badge push: push-type background, priority 5 (Apple
    requires 5 for background)."""
    captured_requests: list = []
    transport = _recording_transport(captured_requests)
    client = _client(signing_key_path, transport)

    client.send_bulk(
        ["token-a"],
        {"aps": {"badge": 0, "content-available": 1}},
        push_type="background",
        priority=5,
    )

    assert captured_requests[0].headers["apns-push-type"] == "background"
    assert captured_requests[0].headers["apns-priority"] == "5"


def test_send_bulk_background_payload_round_trip_byte_identical(signing_key_path):
    """S68 — pin the silent shape so a future refactor can't add a sound /
    alert field: the body on the wire equals the body passed in."""
    captured_requests: list = []
    transport = _recording_transport(captured_requests)
    client = _client(signing_key_path, transport)
    silent_payload = {"aps": {"badge": 3, "content-available": 1}}

    client.send_bulk(["token-a"], silent_payload, push_type="background", priority=5)

    assert json.loads(captured_requests[0].content) == silent_payload


def test_network_error_yields_failed_result_not_exception(signing_key_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(signing_key_path, httpx.MockTransport(handler))

    results = client.send_bulk(["token-a"], {"aps": {}})

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].status == 0
