"""Multi-key resolution, seat limits, and resource usage."""
from datetime import timedelta

import pytest

from vbwd.security.licensing.license_context import (
    LicenseContext,
    NullLicenseContext,
)
from vbwd.security.licensing.license_key import LicenseStatus
from vbwd.security.licensing.license_store import LicenseStore
from vbwd.security.licensing.verifier import LicenseVerifier

from .conftest import FIXED_NOW, FIXTURE_INSTANCE_ID, make_license_key, mint_envelope


@pytest.fixture
def store(tmp_path, signer, fixed_clock):
    verifier = LicenseVerifier(signer, FIXTURE_INSTANCE_ID, fixed_clock)
    return LicenseStore(str(tmp_path), verifier)


def _write_key_file(tmp_path, key, signer):
    """Persist an envelope directly (a key may expire while already held)."""
    (tmp_path / f"{key.key_id}.vbwd").write_text(mint_envelope(key, signer))


def test_platform_wildcard_covers_any_plugin(store, signer):
    store.add(mint_envelope(make_license_key(scope=("*",), seat_limit=25), signer))
    context = LicenseContext(store)
    assert context.has_feature("marketplace") is True
    assert context.has_feature("anything-at-all") is True
    assert context.is_active() is True


def test_plugin_key_covers_only_itself(store, signer):
    store.add(
        mint_envelope(make_license_key(key_id="k-mp", scope=("marketplace",)), signer)
    )
    context = LicenseContext(store)
    assert context.has_feature("marketplace") is True
    assert context.has_feature("analytics") is False


def test_expired_plugin_key_does_not_invalidate_platform_key(store, signer, tmp_path):
    store.add(
        mint_envelope(
            make_license_key(key_id="k-plat", scope=("*",), seat_limit=10), signer
        )
    )
    # The plugin key expired *after* it was stored — write it directly.
    _write_key_file(
        tmp_path,
        make_license_key(
            key_id="k-mp",
            scope=("marketplace",),
            expires_at=FIXED_NOW - timedelta(days=60),
            grace_days=14,
        ),
        signer,
    )
    context = LicenseContext(store)
    # Platform key still active and covering; the expired plugin key coexists
    # with its own EXPIRED status without invalidating the platform key.
    assert context.is_active() is True
    assert context.has_feature("cms") is True  # covered by platform "*"
    statuses = {key.key_id: status for key, status in store.all()}
    assert statuses["k-plat"] is LicenseStatus.VALID
    assert statuses["k-mp"] is LicenseStatus.EXPIRED


def test_within_seat_limit_uses_platform_key(store, signer):
    store.add(mint_envelope(make_license_key(scope=("*",), seat_limit=25), signer))
    context = LicenseContext(store)
    assert context.within_seat_limit(25) is True
    assert context.within_seat_limit(26) is False


def test_resource_usage_reports_seat_limit(store, signer):
    store.add(mint_envelope(make_license_key(scope=("*",), seat_limit=42), signer))
    context = LicenseContext(store)
    seats = next(r for r in context.resource_usage() if r["resource"] == "seats")
    assert seats["limit"] == 42


def test_declared_features_report_coverage(store, signer):
    store.add(mint_envelope(make_license_key(scope=("marketplace",)), signer))
    context = LicenseContext(
        store, feature_registry=lambda: ["marketplace", "analytics"]
    )
    coverage = {row["feature"]: row["licensed"] for row in context.declared_features()}
    assert coverage == {"marketplace": True, "analytics": False}


def test_null_context_is_permissive():
    context = NullLicenseContext()
    assert context.has_feature("anything") is True
    assert context.is_active() is True
    assert context.within_seat_limit(10_000) is True
    assert context.resource_usage() == []


# --- S144.3: optional online gate combines offline AND online coverage ------


def test_no_online_gate_is_identical_to_today(store, signer):
    # The no-URL / offline-only path: default gate is None, behaviour unchanged.
    store.add(mint_envelope(make_license_key(scope=("*",)), signer))
    context = LicenseContext(store)
    assert context.is_active() is True
    assert context.has_feature("marketplace") is True


def test_online_gate_veto_removes_coverage(store, signer):
    # Offline VALID but the online layer vetoes → not covered (online wins).
    store.add(mint_envelope(make_license_key(scope=("*",)), signer))
    context = LicenseContext(store, online_gate=lambda key, status: False)
    assert context.is_active() is False
    assert context.has_feature("marketplace") is False


def test_online_gate_approve_keeps_offline_coverage(store, signer):
    store.add(mint_envelope(make_license_key(scope=("*",)), signer))
    context = LicenseContext(store, online_gate=lambda key, status: True)
    assert context.is_active() is True
    assert context.has_feature("marketplace") is True
