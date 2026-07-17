"""``build_license_environment`` — open / covered / degraded assembly."""
import os

from vbwd.security.licensing.license_context import (
    LicenseContext,
    NullLicenseContext,
)
from vbwd.security.licensing.loader import build_license_environment

from .conftest import FIXTURE_INSTANCE_ID, make_license_key, mint_envelope


def _write_key(keys_dir, key, signer):
    os.makedirs(keys_dir, exist_ok=True)
    with open(os.path.join(keys_dir, f"{key.key_id}.vbwd"), "w", encoding="utf-8") as f:
        f.write(mint_envelope(key, signer))


def test_not_required_no_keys_is_open_null_context(tmp_path, fixed_clock):
    env = build_license_environment(
        {"LICENSE_REQUIRED": False, "LICENSE_KEYS_DIR": str(tmp_path)},
        clock=fixed_clock,
    )
    assert isinstance(env.context, NullLicenseContext)
    assert env.degraded is False
    assert env.store is None


def test_required_with_covering_key_is_active(tmp_path, signer, fixed_clock):
    keys_dir = str(tmp_path / "keys")
    _write_key(keys_dir, make_license_key(scope=("*",)), signer)
    env = build_license_environment(
        {
            "LICENSE_REQUIRED": True,
            "LICENSE_KEYS_DIR": keys_dir,
            "LICENSE_INSTANCE_ID": FIXTURE_INSTANCE_ID,
        },
        signature_verifier=signer,
        clock=fixed_clock,
    )
    assert isinstance(env.context, LicenseContext)
    assert env.context.is_active() is True
    assert env.context.has_feature("marketplace") is True
    assert env.degraded is False


def test_required_without_key_is_degraded(tmp_path, signer, fixed_clock):
    env = build_license_environment(
        {
            "LICENSE_REQUIRED": True,
            "LICENSE_KEYS_DIR": str(tmp_path / "keys"),
            "LICENSE_INSTANCE_ID": FIXTURE_INSTANCE_ID,
        },
        signature_verifier=signer,
        clock=fixed_clock,
    )
    assert env.degraded is True
    assert env.context.is_active() is False
    assert env.context.has_feature("marketplace") is False


def test_required_without_verifier_degrades_not_open(tmp_path, fixed_clock):
    env = build_license_environment(
        {"LICENSE_REQUIRED": True, "LICENSE_KEYS_DIR": str(tmp_path / "keys")},
        clock=fixed_clock,
    )
    # Misconfigured enforcement must degrade, never fall open.
    assert env.degraded is True
    assert env.context.has_feature("marketplace") is False
