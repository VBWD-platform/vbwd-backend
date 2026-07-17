"""License key value object, status enum, and the signed-envelope grammar.

Core-agnostic infrastructure: a ``LicenseKey`` is a signed, scoped grant that
the client *verifies* (it never mints one). This module names no product,
plugin, or feature — the ``scope`` tuple carries whatever ids the signer put in
it (``"*"`` for a platform-wide grant, or opaque plugin/bundle ids).

The wire format is a detached-signature envelope::

    base64url(payload_json) + "." + base64url(signature)

``payload_json`` is the canonical (sorted-key, compact) JSON encoding of the
claims. Keeping the encode/split helpers here means the verifier, the store, and
any signer (tests, the future authority) share one grammar (DRY).
"""
import base64
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

# A scope entry that covers every feature — the platform / edition grant.
WILDCARD_SCOPE = "*"

# Separator between the encoded payload and the encoded signature in an
# envelope. base64url output never contains it, so a single split is safe.
ENVELOPE_SEPARATOR = "."


class LicenseStatus(Enum):
    """The verification outcome for a single key."""

    VALID = "valid"
    GRACE = "grace"
    EXPIRED = "expired"
    INVALID_SIGNATURE = "invalid_signature"
    WRONG_INSTANCE = "wrong_instance"
    MISSING = "missing"


@dataclass(frozen=True)
class LicenseKey:
    """An immutable, signed grant. One key = one SKU/subscription."""

    key_id: str
    customer: str
    instance_id: str
    edition: str
    scope: Tuple[str, ...]
    seat_limit: int
    issued_at: datetime
    expires_at: datetime
    grace_days: int
    nonce: str
    # The authority's public licence identifier (8-byte hex). The authority's
    # ``/verify`` endpoint is keyed on it, so an online status check needs it.
    # OPTIONAL (S144.1a): a pre-existing v1 key has none — the online gate then
    # defers to the offline result. Minting sets it starting in S144.1b.
    license_number: Optional[str] = None

    def covers(self, feature: str) -> bool:
        """Whether this key's scope grants ``feature`` (wildcard covers all)."""
        return WILDCARD_SCOPE in self.scope or feature in self.scope

    @property
    def is_platform_scope(self) -> bool:
        """Whether this is the platform/edition key (global seats + wildcard)."""
        return WILDCARD_SCOPE in self.scope


def encode_license_payload(key: LicenseKey) -> bytes:
    """Serialize a key's claims to canonical JSON bytes (the signed message)."""
    claims = {
        "key_id": key.key_id,
        "customer": key.customer,
        "instance_id": key.instance_id,
        "edition": key.edition,
        "scope": list(key.scope),
        "seat_limit": key.seat_limit,
        "issued_at": key.issued_at.isoformat(),
        "expires_at": key.expires_at.isoformat(),
        "grace_days": key.grace_days,
        "nonce": key.nonce,
    }
    # Emit ``license_number`` ONLY when set, so a key without one produces the
    # exact byte string a pre-existing v1 envelope carried (back-compat: old
    # envelopes keep verifying, the round-trip contract stays green).
    if key.license_number is not None:
        claims["license_number"] = key.license_number
    return json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode_license_payload(payload: bytes, grace_days_fallback: int = 0) -> LicenseKey:
    """Parse canonical JSON bytes back into a :class:`LicenseKey`.

    ``grace_days_fallback`` is used only when the payload omits ``grace_days``
    (an operator/build-level default, sprint §2.6). Raises ``ValueError`` (or
    ``KeyError``) on otherwise-malformed input; the verifier maps that to
    ``INVALID_SIGNATURE`` so a corrupt payload never becomes a key.
    """
    claims = json.loads(payload.decode("utf-8"))
    grace_days = claims.get("grace_days")
    return LicenseKey(
        key_id=claims["key_id"],
        customer=claims["customer"],
        instance_id=claims["instance_id"],
        edition=claims["edition"],
        scope=tuple(claims["scope"]),
        seat_limit=int(claims["seat_limit"]),
        issued_at=datetime.fromisoformat(claims["issued_at"]),
        expires_at=datetime.fromisoformat(claims["expires_at"]),
        grace_days=int(grace_days if grace_days is not None else grace_days_fallback),
        nonce=claims["nonce"],
        # Absent on a v1 envelope → ``None`` (no online enforcement for it).
        license_number=claims.get("license_number"),
    )


def base64url_encode(raw: bytes) -> str:
    """URL-safe base64 without padding (compact, copy-paste friendly)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def base64url_decode(text: str) -> bytes:
    """Inverse of :func:`base64url_encode`; restores the stripped padding."""
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def encode_envelope(payload: bytes, signature: bytes) -> str:
    """Build the ``payload.signature`` envelope string from raw bytes."""
    return base64url_encode(payload) + ENVELOPE_SEPARATOR + base64url_encode(signature)


def split_envelope(envelope: str) -> Tuple[bytes, bytes]:
    """Split an envelope into ``(payload_bytes, signature_bytes)``.

    Raises ``ValueError`` on a structurally malformed envelope so the verifier
    can classify it as ``INVALID_SIGNATURE``.
    """
    if ENVELOPE_SEPARATOR not in envelope:
        raise ValueError("Envelope is missing the payload/signature separator")
    payload_part, signature_part = envelope.rsplit(ENVELOPE_SEPARATOR, 1)
    return base64url_decode(payload_part), base64url_decode(signature_part)
