"""Online licence-status providers (S144.3) — the read-only verify channel.

A consuming instance's core asks the authority whether a licence is still live:
``POST {authority}/api/v1/license/verify {"license_number": "<hex>"}`` →
``{"status": "active"|"inactive"|"revoked"|"unknown", "checked_at": "<iso>"}``.
This is public and needs **no API key** (the box only *holds* the licence).

The HTTP transport sits behind an injected client (DIP) so tests use a fake and
never open a socket. Any transport failure degrades to ``reachable=False`` — the
provider never raises out, so the resolver can apply the fail-soft/grace policy.
``NullLicenseStatusProvider`` is the CE default when no authority URL is
configured: it reports "not configured" (unreachable), i.e. offline-only, exactly
as S135 behaves today.
"""
from datetime import datetime
from typing import Optional

import requests

from vbwd.security.licensing.ports import (
    AuthorityStatus,
    ILicenseStatusProvider,
    LicenseAuthorityStatus,
)

VERIFY_PATH = "/api/v1/license/verify"
DEFAULT_TIMEOUT_SECONDS = 10

_HTTP_OK = 200

# The authoritative verdicts the authority may report on the wire.
_WIRE_STATUSES = {status.value: status for status in AuthorityStatus}


def _unreachable() -> LicenseAuthorityStatus:
    """The "no authoritative answer" result (network error / no URL)."""
    return LicenseAuthorityStatus(
        status=AuthorityStatus.UNKNOWN, checked_at=None, reachable=False
    )


def _parse_checked_at(raw: object) -> Optional[datetime]:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


class HttpLicenseStatusProvider(ILicenseStatusProvider):
    """Calls the authority's ``verify`` endpoint over the injected http client."""

    def __init__(
        self,
        authority_url: str,
        http_client=requests,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        identity_envelope: Optional[str] = None,
    ) -> None:
        self._authority_url = authority_url.rstrip("/")
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds
        self._identity_envelope = identity_envelope

    @property
    def identity_envelope(self) -> Optional[str]:
        """The box's own raw signed envelope sent as proof-of-identity, or None.

        A construction-time property only: when set, the verify body carries it
        alongside ``license_number`` so a broker (vbwd.cc) can confirm the caller
        is a known instance before forwarding to a private authority. ``None``
        keeps the body byte-for-byte as before (the no-regression case).
        """
        return self._identity_envelope

    def status(self, license_number: str) -> LicenseAuthorityStatus:
        request_body = {"license_number": license_number}
        if self._identity_envelope is not None:
            request_body["envelope"] = self._identity_envelope
        try:
            response = self._http_client.post(
                f"{self._authority_url}{VERIFY_PATH}",
                json=request_body,
                timeout=self._timeout_seconds,
            )
        except requests.RequestException:
            return _unreachable()

        if response.status_code != _HTTP_OK:
            return _unreachable()

        body = response.json() or {}
        wire_status = body.get("status")
        status = (
            _WIRE_STATUSES.get(wire_status) if isinstance(wire_status, str) else None
        )
        if status is None:
            return _unreachable()
        return LicenseAuthorityStatus(
            status=status,
            checked_at=_parse_checked_at(body.get("checked_at")),
            reachable=True,
        )


class NullLicenseStatusProvider(ILicenseStatusProvider):
    """CE default when no authority URL is set — always "not configured".

    Reports ``reachable=False`` so effective coverage falls back to the offline
    signature/expiry check alone (S135), byte-for-byte as today.
    """

    def status(self, license_number: str) -> LicenseAuthorityStatus:
        return _unreachable()
