"""Envelope grammar (S144.1a) — ``license_number`` rides the signed claims.

The authority's ``/verify`` endpoint is keyed on the 8-byte-hex
``license_number``, so a consuming instance must carry it in the signed
envelope to check online status. It is OPTIONAL (default ``None``): a
pre-existing v1 envelope with no ``license_number`` claim still decodes and
verifies unchanged (byte-for-byte back-compat).
"""
import json

from vbwd.security.licensing.license_key import (
    LicenseStatus,
    decode_license_payload,
    encode_license_payload,
)
from vbwd.security.licensing.verifier import LicenseVerifier

from .conftest import FIXTURE_INSTANCE_ID, make_license_key, mint_envelope


def test_license_number_round_trips_when_set():
    key = make_license_key(license_number="A1B2C3D4")
    decoded = decode_license_payload(encode_license_payload(key))
    assert decoded.license_number == "A1B2C3D4"


def test_license_number_absent_decodes_to_none():
    decoded = decode_license_payload(encode_license_payload(make_license_key()))
    assert decoded.license_number is None


def test_v1_payload_omits_license_number_claim_and_decodes_to_none():
    # When unset the claim is NOT emitted — the signed bytes stay byte-identical
    # to a pre-existing v1 envelope, so old envelopes verify unchanged.
    payload = encode_license_payload(make_license_key())
    claims = json.loads(payload.decode("utf-8"))
    assert "license_number" not in claims
    assert decode_license_payload(payload).license_number is None


def test_v1_shaped_envelope_still_verifies_valid(signer, fixed_clock):
    envelope = mint_envelope(make_license_key(), signer)
    decoded, status = LicenseVerifier(signer, FIXTURE_INSTANCE_ID, fixed_clock).verify(
        envelope
    )
    assert status is LicenseStatus.VALID
    assert decoded is not None
    assert decoded.license_number is None


def test_envelope_with_license_number_verifies_valid(signer, fixed_clock):
    envelope = mint_envelope(make_license_key(license_number="DEADBEEF"), signer)
    decoded, status = LicenseVerifier(signer, FIXTURE_INSTANCE_ID, fixed_clock).verify(
        envelope
    )
    assert status is LicenseStatus.VALID
    assert decoded is not None
    assert decoded.license_number == "DEADBEEF"
