"""The test-run licence harness (keyless gap, 2026-10-06).

A keyless install grants no licensed feature, so a suite that needs a
licence-requiring plugin active must hold a real licence — never a weakened
gate. The repo-root ``conftest.py`` mints one per test session with a throwaway
Ed25519 key through ``vbwd.testing.license_harness``; these specs pin that the
minted licence verifies through the REAL production path (Ed25519 verifier,
instance fingerprint, ``build_license_environment``).
"""
import os

from nacl.signing import SigningKey

from vbwd.config import get_database_url
from vbwd.security.licensing.license_key import base64url_encode
from vbwd.security.licensing.loader import build_license_environment
from vbwd.testing.license_harness import write_test_licenses

DATABASE_URL = "postgresql://vbwd:vbwd@db-host-under-test:5432/vbwd_test"
ANY_LICENSED_FEATURE = "any-licensed-feature"


def _environment_for(public_key: str, keys_dir: str, database_url: str):
    return build_license_environment(
        {
            "LICENSE_PUBLIC_KEY": public_key,
            "LICENSE_KEYS_DIR": keys_dir,
            "SQLALCHEMY_DATABASE_URI": database_url,
        }
    )


def test_minted_test_licence_covers_every_feature_via_the_real_verifier(tmp_path):
    signing_key = SigningKey.generate()
    keys_dir = str(tmp_path / "license" / "keys")

    write_test_licenses(signing_key, keys_dir, DATABASE_URL)

    public_key = base64url_encode(bytes(signing_key.verify_key))
    context = _environment_for(public_key, keys_dir, DATABASE_URL).context
    assert context.has_feature(ANY_LICENSED_FEATURE) is True


def test_minted_test_licence_is_rejected_under_another_public_key(tmp_path):
    keys_dir = str(tmp_path / "license" / "keys")
    write_test_licenses(SigningKey.generate(), keys_dir, DATABASE_URL)

    other_public_key = base64url_encode(bytes(SigningKey.generate().verify_key))
    context = _environment_for(other_public_key, keys_dir, DATABASE_URL).context
    assert context.has_feature(ANY_LICENSED_FEATURE) is False


def test_the_test_session_holds_a_covering_test_licence():
    """The root conftest points the licence env at a covering test licence."""
    public_key = os.environ.get("VBWD_LICENSE_PUBLIC_KEY")
    keys_dir = os.environ.get("VBWD_LICENSE_KEYS_DIR")

    assert public_key and keys_dir
    context = _environment_for(public_key, keys_dir, get_database_url()).context
    assert context.has_feature(ANY_LICENSED_FEATURE) is True


def test_a_dict_configured_app_holds_the_test_licence():
    """``create_app(config_dict)`` skips ``vbwd.config``; the harness must still
    reach the dict-configured apps every suite builds."""
    from vbwd.app import create_app

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": get_database_url(),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "RATELIMIT_STORAGE_URL": "memory://",
        }
    )

    assert app.license_context.has_feature(ANY_LICENSED_FEATURE) is True


def test_an_explicit_keyless_config_still_opts_out(tmp_path):
    from vbwd.app import create_app

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": get_database_url(),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "RATELIMIT_STORAGE_URL": "memory://",
            "LICENSE_PUBLIC_KEY": None,
            # A missing keys dir under tmp_path: the instance salt is written to its
            # parent, which must be writable (CI runners are not root).
            "LICENSE_KEYS_DIR": str(tmp_path / "license" / "keys"),
        }
    )

    assert app.license_context.has_feature(ANY_LICENSED_FEATURE) is False
