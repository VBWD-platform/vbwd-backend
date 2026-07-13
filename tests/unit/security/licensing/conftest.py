"""Shared fixtures for the license-gate unit suite.

Tests inject a FIXTURE signature verifier (a deterministic HMAC double that
honours the ``ISignatureVerifier`` contract) and mint fixture-signed envelopes —
no real Ed25519 key is needed at test time. Flipping any payload byte breaks the
signature exactly as a real signature would, so the status matrix is exercised
faithfully.
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import pytest

from vbwd.security.licensing.license_key import (
    LicenseKey,
    encode_envelope,
    encode_license_payload,
)
from vbwd.security.licensing.ports import ISignatureVerifier

FIXED_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
FIXTURE_INSTANCE_ID = "instance-fingerprint-abc"


class FixtureSignatureVerifier(ISignatureVerifier):
    """A deterministic HMAC stand-in for the Ed25519 verifier (Liskov-safe)."""

    def __init__(self, secret: bytes = b"vbwd-fixture-secret") -> None:
        self._secret = secret

    def sign(self, message: bytes) -> bytes:
        return hmac.new(self._secret, message, hashlib.sha256).digest()

    def verify(self, message: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(self.sign(message), signature)


def make_license_key(**overrides) -> LicenseKey:
    """Build a LicenseKey with sensible defaults; override any field."""
    defaults = dict(
        key_id="key-platform",
        customer="acme-gmbh",
        instance_id=FIXTURE_INSTANCE_ID,
        edition="ME",
        scope=("*",),
        seat_limit=25,
        issued_at=FIXED_NOW - timedelta(days=1),
        expires_at=FIXED_NOW + timedelta(days=365),
        grace_days=14,
        nonce="nonce-1",
    )
    defaults.update(overrides)
    return LicenseKey(**defaults)


def mint_envelope(key: LicenseKey, signer: FixtureSignatureVerifier) -> str:
    """Sign a key's payload with the fixture signer into a wire envelope."""
    payload = encode_license_payload(key)
    return encode_envelope(payload, signer.sign(payload))


@pytest.fixture
def signer() -> FixtureSignatureVerifier:
    return FixtureSignatureVerifier()


@pytest.fixture
def fixed_clock():
    return lambda: FIXED_NOW
