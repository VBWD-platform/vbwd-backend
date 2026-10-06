"""Test-only licence minting for the test run (keyless gap, 2026-10-06).

A keyless install grants no licensed feature, so a test suite that needs a
licence-requiring plugin active must hold a REAL licence rather than weaken the
gate. The repo-root ``conftest.py`` generates a throwaway Ed25519 key per test
session, points ``VBWD_LICENSE_PUBLIC_KEY`` / ``VBWD_LICENSE_KEYS_DIR`` at it,
and calls :func:`write_test_licenses` to mint a wildcard licence bound to the
test instance's fingerprint. The private half never leaves the test process, so
nothing minted here can verify on any other instance.

Core test infrastructure — agnostic, names no plugin or feature.
"""
import os
from datetime import datetime, timedelta, timezone

from nacl.signing import SigningKey

from vbwd.security.licensing.instance_fingerprint import (
    database_host_from_url,
    compute_instance_fingerprint,
    load_or_create_salt,
)
from vbwd.security.licensing.license_key import (
    WILDCARD_SCOPE,
    LicenseKey,
    encode_envelope,
    encode_license_payload,
)

TEST_LICENSE_KEY_ID = "test-run-platform"
TEST_LICENSE_VALIDITY_DAYS = 3650
TEST_LICENSE_SEAT_LIMIT = 1000
TEST_LICENSE_GRACE_DAYS = 0


def write_test_licenses(
    signing_key: SigningKey, keys_dir: str, database_url: str
) -> None:
    """Mint a wildcard test licence into ``keys_dir`` for ``database_url``'s host.

    The instance fingerprint is computed exactly as the boot path does (DB host
    + the salt persisted beside ``keys_dir``), so the licence verifies through
    the real ``build_license_environment`` for any app on that database host.
    """
    os.makedirs(keys_dir, exist_ok=True)
    salt = load_or_create_salt(os.path.dirname(keys_dir))
    instance_id = compute_instance_fingerprint(
        database_host_from_url(database_url), salt
    )
    issued_at = datetime.now(timezone.utc)
    license_key = LicenseKey(
        key_id=TEST_LICENSE_KEY_ID,
        customer="vbwd test run",
        instance_id=instance_id,
        edition="test",
        scope=(WILDCARD_SCOPE,),
        seat_limit=TEST_LICENSE_SEAT_LIMIT,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(days=TEST_LICENSE_VALIDITY_DAYS),
        grace_days=TEST_LICENSE_GRACE_DAYS,
        nonce=TEST_LICENSE_KEY_ID,
    )
    payload = encode_license_payload(license_key)
    envelope = encode_envelope(payload, signing_key.sign(payload).signature)
    key_path = os.path.join(keys_dir, f"{TEST_LICENSE_KEY_ID}.vbwd")
    with open(key_path, "w", encoding="utf-8") as key_file:
        key_file.write(envelope)
