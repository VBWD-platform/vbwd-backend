"""``build_license_environment`` — open / covered / degraded assembly."""
import os

from vbwd.security.licensing.license_context import (
    LicenseContext,
    NullLicenseContext,
)
from vbwd.security.licensing.loader import build_license_environment
from vbwd.security.licensing.ports import (
    AuthorityStatus,
    ILicenseStatusProvider,
    LicenseAuthorityStatus,
)
from vbwd.security.licensing.status_provider import (
    HttpLicenseStatusProvider,
    NullLicenseStatusProvider,
)

from .conftest import FIXTURE_INSTANCE_ID, make_license_key, mint_envelope


class _FixedStatusProvider(ILicenseStatusProvider):
    """A fake authority verdict — no socket. ``reachable`` drives fail-soft."""

    def __init__(self, status: AuthorityStatus, reachable: bool = True) -> None:
        self._status = status
        self._reachable = reachable

    def status(self, license_number: str) -> LicenseAuthorityStatus:
        return LicenseAuthorityStatus(
            self._status, checked_at=None, reachable=self._reachable
        )


_AUTHORITY_URL = "https://authority.example"
_LICENSE_NUMBER = "A1B2C3D4"


def _covered_env(tmp_path, signer, fixed_clock, key, url_config, provider):
    keys_dir = str(tmp_path / "keys")
    _write_key(keys_dir, key, signer)
    config = {
        "LICENSE_REQUIRED": True,
        "LICENSE_KEYS_DIR": keys_dir,
        "LICENSE_INSTANCE_ID": FIXTURE_INSTANCE_ID,
    }
    config.update(url_config)
    return build_license_environment(
        config,
        signature_verifier=signer,
        status_provider=provider,
        clock=fixed_clock,
    )


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


def test_no_authority_url_uses_null_status_provider(tmp_path, fixed_clock):
    # CE default (no authority URL) → offline-only, exactly as S135 today.
    env = build_license_environment(
        {"LICENSE_REQUIRED": False, "LICENSE_KEYS_DIR": str(tmp_path)},
        clock=fixed_clock,
    )
    assert isinstance(env.context, NullLicenseContext)
    assert isinstance(env.status_provider, NullLicenseStatusProvider)


def test_authority_url_builds_http_status_provider(tmp_path, fixed_clock):
    env = build_license_environment(
        {
            "LICENSE_REQUIRED": False,
            "LICENSE_KEYS_DIR": str(tmp_path),
            "VBWD_LICENSE_AUTHORITY_URL": "https://authority.example",
        },
        clock=fixed_clock,
    )
    assert isinstance(env.status_provider, HttpLicenseStatusProvider)


# --- S144.1a: the online gate is wired only with URL + license_number --------


def test_online_gate_inactive_authority_removes_coverage(tmp_path, signer, fixed_clock):
    # URL set + key carries license_number + authority says inactive ⇒ NOT covered
    # even though the offline signature is VALID (online status wins).
    env = _covered_env(
        tmp_path,
        signer,
        fixed_clock,
        make_license_key(scope=("*",), license_number=_LICENSE_NUMBER),
        {"VBWD_LICENSE_AUTHORITY_URL": _AUTHORITY_URL},
        _FixedStatusProvider(AuthorityStatus.INACTIVE),
    )
    assert env.context.is_active() is False
    assert env.context.has_feature("marketplace") is False


def test_online_gate_active_authority_keeps_coverage(tmp_path, signer, fixed_clock):
    env = _covered_env(
        tmp_path,
        signer,
        fixed_clock,
        make_license_key(scope=("*",), license_number=_LICENSE_NUMBER),
        {"VBWD_LICENSE_AUTHORITY_URL": _AUTHORITY_URL},
        _FixedStatusProvider(AuthorityStatus.ACTIVE),
    )
    assert env.context.is_active() is True
    assert env.context.has_feature("marketplace") is True


def test_online_gate_defers_for_v1_key_without_license_number(
    tmp_path, signer, fixed_clock
):
    # URL set but the key has NO license_number (v1) ⇒ gate defers to offline;
    # covered because the offline status is VALID, authority verdict ignored.
    env = _covered_env(
        tmp_path,
        signer,
        fixed_clock,
        make_license_key(scope=("*",)),
        {"VBWD_LICENSE_AUTHORITY_URL": _AUTHORITY_URL},
        _FixedStatusProvider(AuthorityStatus.INACTIVE),
    )
    assert env.context.is_active() is True


def test_online_gate_failsoft_unreachable_holds_offline_coverage(
    tmp_path, signer, fixed_clock
):
    # URL set + license_number + authority unreachable + offline VALID ⇒ covered
    # (fail-soft: an authority outage never bricks a paying customer).
    env = _covered_env(
        tmp_path,
        signer,
        fixed_clock,
        make_license_key(scope=("*",), license_number=_LICENSE_NUMBER),
        {"VBWD_LICENSE_AUTHORITY_URL": _AUTHORITY_URL},
        _FixedStatusProvider(AuthorityStatus.UNKNOWN, reachable=False),
    )
    assert env.context.is_active() is True


def test_no_authority_url_is_offline_only(tmp_path, signer, fixed_clock):
    # No URL ⇒ no online gate ⇒ covered on the offline signature alone, exactly
    # as S135 today (even with a license_number present on the key).
    env = _covered_env(
        tmp_path,
        signer,
        fixed_clock,
        make_license_key(scope=("*",), license_number=_LICENSE_NUMBER),
        {},
        None,
    )
    assert env.context.is_active() is True
