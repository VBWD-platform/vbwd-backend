"""APNs HTTP/2 transport client (S66).

Pure transport (Liskov): sends an opaque payload to a list of device tokens
and returns a per-token result. It NEVER mutates device-token rows — a 410
("Unregistered") is surfaced to the caller, and the caller (the plugin push
hook) decides to revoke.

Authentication is Apple's provider-token scheme: an ES256-signed JWT with the
key id (``kid``) in the header and the team id (``iss``) + ``iat`` as claims,
cached and re-signed every ~50 minutes (Apple accepts 20–60 min old tokens).

Graceful degradation: when the ``.p8`` signing key is unset or unreadable the
client logs ONE warning (at construction, i.e. plugin-enable/boot time) and
``send_bulk`` is a no-op — dev/CI without Apple credentials keeps working.
"""
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx
import jwt

logger = logging.getLogger(__name__)

APNS_PRODUCTION_HOST = "https://api.push.apple.com"
APNS_SANDBOX_HOST = "https://api.sandbox.push.apple.com"

# Apple requires the provider token to be 20–60 minutes old at most;
# re-sign comfortably inside that window.
PROVIDER_TOKEN_REFRESH_SECONDS = 50 * 60

# A transport-level failure (connect error, timeout) has no HTTP status.
TRANSPORT_FAILURE_STATUS = 0

# Module-level flag so a missing key warns once per process, not once per
# constructed client (meinchat + meinchat-plus each build one).
_missing_key_warning_emitted = False


@dataclass
class ApnsSendResult:
    """Per-token outcome of a bulk send."""

    token: str
    success: bool
    status: int
    reason: Optional[str] = None


class ApnsClient:
    """HTTP/2 APNs sender with ES256 provider-token auth."""

    def __init__(
        self,
        *,
        key_path: Optional[str],
        key_id: str,
        team_id: str,
        bundle_id: str,
        use_sandbox: bool = False,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._key_id = key_id
        self._team_id = team_id
        self._bundle_id = bundle_id
        self._use_sandbox = use_sandbox
        self._transport = transport
        self._signing_key = self._load_signing_key(key_path)
        self._provider_token: Optional[str] = None
        self._provider_token_issued_at = 0.0
        self._http_client: Optional[httpx.Client] = None

    @property
    def enabled(self) -> bool:
        """False when no signing key could be loaded (send_bulk is a no-op)."""
        return self._signing_key is not None

    def send_bulk(
        self,
        device_tokens: List[str],
        payload: Dict,
        *,
        push_type: str = "alert",
        priority: int = 10,
    ) -> List[ApnsSendResult]:
        """POST ``payload`` to every token; return one result per token.

        ``push_type`` / ``priority`` set the ``apns-push-type`` and
        ``apns-priority`` headers. The defaults (``"alert"`` / ``10``) keep
        the S66 alert path byte-identical; a silent badge push passes
        ``push_type="background", priority=5`` (Apple requires 5 for
        background pushes)."""
        if not self.enabled:
            return []
        headers = {
            "authorization": f"bearer {self._current_provider_token()}",
            "apns-topic": self._bundle_id,
            "apns-push-type": push_type,
            "apns-priority": str(priority),
        }
        http_client = self._client()
        results: List[ApnsSendResult] = []
        for device_token in device_tokens:
            results.append(self._send_one(http_client, device_token, payload, headers))
        return results

    # ── internals ───────────────────────────────────────────────────────────

    def _send_one(
        self,
        http_client: httpx.Client,
        device_token: str,
        payload: Dict,
        headers: Dict[str, str],
    ) -> ApnsSendResult:
        url = f"{self._host()}/3/device/{device_token}"
        try:
            response = http_client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as error:
            logger.warning("APNs send to %s… failed: %s", device_token[:8], error)
            return ApnsSendResult(
                token=device_token,
                success=False,
                status=TRANSPORT_FAILURE_STATUS,
                reason=str(error),
            )
        success = response.status_code == 200
        return ApnsSendResult(
            token=device_token,
            success=success,
            status=response.status_code,
            reason=None if success else self._reason_of(response),
        )

    @staticmethod
    def _reason_of(response: httpx.Response) -> Optional[str]:
        """APNs error bodies are ``{"reason": "..."}``; tolerate anything else."""
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(body, dict):
            return body.get("reason")
        return None

    def _host(self) -> str:
        return APNS_SANDBOX_HOST if self._use_sandbox else APNS_PRODUCTION_HOST

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            if self._transport is not None:
                self._http_client = httpx.Client(transport=self._transport)
            else:
                # Real APNs requires HTTP/2 (needs the ``h2`` package).
                self._http_client = httpx.Client(http2=True)
        return self._http_client

    def _current_provider_token(self) -> str:
        signing_key = self._signing_key
        if signing_key is None:
            # Defensive: send_bulk no-ops via ``enabled`` before reaching here.
            raise RuntimeError("APNs signing key is not loaded")
        now = time.time()
        expired = now - self._provider_token_issued_at > PROVIDER_TOKEN_REFRESH_SECONDS
        if self._provider_token is None or expired:
            self._provider_token = jwt.encode(
                {"iss": self._team_id, "iat": int(now)},
                signing_key,
                algorithm="ES256",
                headers={"kid": self._key_id},
            )
            self._provider_token_issued_at = now
        return self._provider_token

    @staticmethod
    def _load_signing_key(key_path: Optional[str]) -> Optional[str]:
        global _missing_key_warning_emitted
        if key_path:
            try:
                with open(key_path) as key_file:
                    return key_file.read()
            except OSError as error:
                detail = f"unreadable ({error})"
        else:
            detail = "unset"
        if not _missing_key_warning_emitted:
            logger.warning(
                "VBWD_APNS_KEY_PATH is %s — APNs pushes are disabled "
                "(send_bulk is a no-op).",
                detail,
            )
            _missing_key_warning_emitted = True
        return None


def apns_client_from_env() -> ApnsClient:
    """Build an ``ApnsClient`` from the ``VBWD_APNS_*`` environment variables."""
    return ApnsClient(
        key_path=os.environ.get("VBWD_APNS_KEY_PATH"),
        key_id=os.environ.get("VBWD_APNS_KEY_ID", ""),
        team_id=os.environ.get("VBWD_APNS_TEAM_ID", ""),
        bundle_id=os.environ.get("VBWD_APNS_BUNDLE_ID", ""),
        use_sandbox=os.environ.get("VBWD_APNS_USE_SANDBOX", "").lower() == "true",
    )
