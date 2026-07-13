"""Status matrix for :class:`LicenseVerifier` (fixture keypair)."""
from datetime import timedelta

from vbwd.security.licensing.license_key import LicenseStatus
from vbwd.security.licensing.verifier import LicenseVerifier

from .conftest import FIXED_NOW, FIXTURE_INSTANCE_ID, make_license_key, mint_envelope


def _verifier(signer, fixed_clock):
    return LicenseVerifier(signer, FIXTURE_INSTANCE_ID, fixed_clock)


def test_valid_key_is_valid(signer, fixed_clock):
    envelope = mint_envelope(make_license_key(), signer)
    key, status = _verifier(signer, fixed_clock).verify(envelope)
    assert status is LicenseStatus.VALID
    assert key is not None and key.key_id == "key-platform"


def test_flipped_signature_byte_is_invalid_signature(signer, fixed_clock):
    envelope = mint_envelope(make_license_key(), signer)
    # Corrupt the last character (the signature tail) to break verification.
    tampered = envelope[:-2] + ("A" if envelope[-1] != "A" else "B")
    key, status = _verifier(signer, fixed_clock).verify(tampered)
    assert status is LicenseStatus.INVALID_SIGNATURE
    assert key is None


def test_within_grace_is_grace(signer, fixed_clock):
    key = make_license_key(expires_at=FIXED_NOW - timedelta(days=2), grace_days=14)
    _key, status = _verifier(signer, fixed_clock).verify(mint_envelope(key, signer))
    assert status is LicenseStatus.GRACE


def test_past_grace_is_expired(signer, fixed_clock):
    key = make_license_key(expires_at=FIXED_NOW - timedelta(days=30), grace_days=14)
    _key, status = _verifier(signer, fixed_clock).verify(mint_envelope(key, signer))
    assert status is LicenseStatus.EXPIRED


def test_mismatched_instance_is_wrong_instance(signer, fixed_clock):
    key = make_license_key(instance_id="a-different-box")
    returned_key, status = _verifier(signer, fixed_clock).verify(
        mint_envelope(key, signer)
    )
    assert status is LicenseStatus.WRONG_INSTANCE
    # The key is still returned (signature was valid) so the tab can show it.
    assert returned_key is not None


def test_empty_envelope_is_missing(signer, fixed_clock):
    key, status = _verifier(signer, fixed_clock).verify(None)
    assert status is LicenseStatus.MISSING
    assert key is None


def test_malformed_envelope_is_invalid_signature(signer, fixed_clock):
    key, status = _verifier(signer, fixed_clock).verify("not-an-envelope")
    assert status is LicenseStatus.INVALID_SIGNATURE
    assert key is None
