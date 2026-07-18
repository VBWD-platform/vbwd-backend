"""Online status providers (S144.3) — HTTP adapter + null default.

The HTTP adapter talks to the authority ``verify`` endpoint through an INJECTED
http client (DIP), so these tests never open a real socket. A network failure
must degrade to ``reachable=False`` — never raise out of the provider.
"""
import pytest
import requests

from vbwd.security.licensing.ports import (
    AuthorityStatus,
    ILicenseStatusProvider,
    LicenseAuthorityStatus,
)
from vbwd.security.licensing.status_provider import (
    VERIFY_PATH,
    HttpLicenseStatusProvider,
    NullLicenseStatusProvider,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _RecordingHttpClient:
    """A fake http client that records the POST and returns a canned response."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self._response


class _UnreachableHttpClient:
    """A fake http client whose POST always raises a transport error."""

    def post(self, url, *, json, timeout):
        raise requests.ConnectionError("authority down")


def test_provider_honours_the_port_contract():
    assert isinstance(NullLicenseStatusProvider(), ILicenseStatusProvider)
    assert isinstance(
        HttpLicenseStatusProvider("https://authority.example"),
        ILicenseStatusProvider,
    )


def test_active_response_is_reachable_active():
    client = _RecordingHttpClient(
        _FakeResponse(
            200, {"status": "active", "checked_at": "2026-06-01T00:00:00+00:00"}
        )
    )
    provider = HttpLicenseStatusProvider(
        "https://authority.example/", http_client=client
    )

    result = provider.status("A1B2C3D4")

    assert result.reachable is True
    assert result.status is AuthorityStatus.ACTIVE
    assert result.checked_at is not None
    # It POSTed the license_number to the verify path — no live socket.
    assert client.calls[0]["url"] == "https://authority.example" + VERIFY_PATH
    assert client.calls[0]["json"] == {"license_number": "A1B2C3D4"}


@pytest.mark.parametrize(
    "wire, expected",
    [
        ("inactive", AuthorityStatus.INACTIVE),
        ("revoked", AuthorityStatus.REVOKED),
        ("unknown", AuthorityStatus.UNKNOWN),
    ],
)
def test_authoritative_statuses_are_reachable(wire, expected):
    client = _RecordingHttpClient(_FakeResponse(200, {"status": wire}))
    provider = HttpLicenseStatusProvider(
        "https://authority.example", http_client=client
    )

    result = provider.status("A1B2C3D4")

    assert result.reachable is True
    assert result.status is expected


def test_network_error_is_unreachable_never_raises():
    provider = HttpLicenseStatusProvider(
        "https://authority.example", http_client=_UnreachableHttpClient()
    )

    result = provider.status("A1B2C3D4")

    assert result.reachable is False
    assert result.status is AuthorityStatus.UNKNOWN
    assert result.checked_at is None


def test_non_200_is_unreachable():
    client = _RecordingHttpClient(_FakeResponse(503, {}))
    provider = HttpLicenseStatusProvider(
        "https://authority.example", http_client=client
    )

    result = provider.status("A1B2C3D4")

    assert result.reachable is False


def test_malformed_body_is_unreachable():
    client = _RecordingHttpClient(_FakeResponse(200, {"nonsense": True}))
    provider = HttpLicenseStatusProvider(
        "https://authority.example", http_client=client
    )

    result = provider.status("A1B2C3D4")

    assert result.reachable is False


def test_envelope_is_omitted_when_no_identity_supplied():
    # Byte-for-byte back-compat: default (no identity envelope) POSTs the
    # license_number ONLY — the authority/broker accept that unchanged.
    client = _RecordingHttpClient(_FakeResponse(200, {"status": "active"}))
    provider = HttpLicenseStatusProvider(
        "https://authority.example", http_client=client
    )

    provider.status("A1B2C3D4")

    assert client.calls[0]["json"] == {"license_number": "A1B2C3D4"}
    assert provider.identity_envelope is None


def test_envelope_is_included_when_identity_supplied():
    # When the box's own signed envelope is supplied, the broker gets it too so
    # it can verify the caller is a known instance before brokering the verify.
    client = _RecordingHttpClient(_FakeResponse(200, {"status": "active"}))
    provider = HttpLicenseStatusProvider(
        "https://authority.example",
        http_client=client,
        identity_envelope="ENVELOPE.SIGNATURE",
    )

    provider.status("A1B2C3D4")

    assert client.calls[0]["json"] == {
        "license_number": "A1B2C3D4",
        "envelope": "ENVELOPE.SIGNATURE",
    }
    assert provider.identity_envelope == "ENVELOPE.SIGNATURE"


def test_null_provider_is_unreachable_unknown():
    result = NullLicenseStatusProvider().status("A1B2C3D4")

    assert result.reachable is False
    assert result.status is AuthorityStatus.UNKNOWN
    assert result.checked_at is None
    assert isinstance(result, LicenseAuthorityStatus)
