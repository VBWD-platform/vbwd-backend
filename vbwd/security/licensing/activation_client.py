"""HTTP activation client — redeems a dashboard code against the license hub.

The online self-serve path: the client POSTs ``{code, instance_id}`` to the hub
and receives an instance-bound signed envelope, which the store then verifies
locally. Kept behind :class:`ILicenseActivationClient` so the routes are unit-
testable with a fake and so the transport is swappable.
"""
import requests

from vbwd.security.licensing.ports import (
    ILicenseActivationClient,
    LicenseActivationError,
)

ACTIVATE_PATH = "/api/v1/license/activate"
DEFAULT_TIMEOUT_SECONDS = 10


class HttpLicenseActivationClient(ILicenseActivationClient):
    """Talks to the hub's ``activate`` endpoint over HTTPS."""

    def __init__(self, hub_url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        self._hub_url = hub_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def activate(self, code: str, instance_id: str) -> str:
        """Exchange a code for a signed envelope. Raises on any failure."""
        try:
            response = requests.post(
                f"{self._hub_url}{ACTIVATE_PATH}",
                json={"code": code, "instance_id": instance_id},
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as error:
            raise LicenseActivationError(f"Hub unreachable: {error}") from error

        if response.status_code != 200:
            raise LicenseActivationError(
                f"Hub rejected activation (HTTP {response.status_code})"
            )

        envelope = (response.json() or {}).get("envelope")
        if not envelope:
            raise LicenseActivationError("Hub response did not include an envelope")
        return envelope
