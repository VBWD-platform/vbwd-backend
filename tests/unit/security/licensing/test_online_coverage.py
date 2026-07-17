"""Effective-coverage resolver (S144.3) — offline AND online, cached, fail-soft.

Effective coverage = the offline signature/expiry result (S135) AND the
authority's live verdict. Online ``inactive``/``revoked`` overrides a valid
signature; on an authority outage we fall back to the licence's own grace
window (offline-only) and hold the last authoritative verdict — never a hard
brick. A ``clock`` is injected; the provider is a fake (no live socket).
"""
from datetime import datetime, timedelta, timezone

from vbwd.security.licensing.license_key import LicenseStatus
from vbwd.security.licensing.online_coverage import OnlineCoverageResolver
from vbwd.security.licensing.ports import (
    AuthorityStatus,
    ILicenseStatusProvider,
    LicenseAuthorityStatus,
)

_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
_LICENSE = "A1B2C3D4"


class _ScriptedProvider(ILicenseStatusProvider):
    """Returns queued answers in order; records how many times it was called."""

    def __init__(self, *answers: LicenseAuthorityStatus) -> None:
        self._answers = list(answers)
        self.call_count = 0

    def status(self, license_number: str) -> LicenseAuthorityStatus:
        self.call_count += 1
        if len(self._answers) == 1:
            return self._answers[0]
        return self._answers.pop(0)


def _active():
    return LicenseAuthorityStatus(AuthorityStatus.ACTIVE, _NOW, reachable=True)


def _inactive():
    return LicenseAuthorityStatus(AuthorityStatus.INACTIVE, _NOW, reachable=True)


def _revoked():
    return LicenseAuthorityStatus(AuthorityStatus.REVOKED, _NOW, reachable=True)


def _unreachable():
    return LicenseAuthorityStatus(AuthorityStatus.UNKNOWN, None, reachable=False)


def _resolver(provider, clock=lambda: _NOW, cache_ttl_seconds=300):
    return OnlineCoverageResolver(provider, clock, cache_ttl_seconds=cache_ttl_seconds)


# --- online status wins over a valid signature -----------------------------


def test_online_active_and_offline_valid_is_covered():
    resolver = _resolver(_ScriptedProvider(_active()))
    assert resolver.is_covered(LicenseStatus.VALID, _LICENSE) is True


def test_online_inactive_over_valid_signature_is_not_covered():
    resolver = _resolver(_ScriptedProvider(_inactive()))
    assert resolver.is_covered(LicenseStatus.VALID, _LICENSE) is False


def test_online_revoked_over_valid_signature_is_not_covered():
    resolver = _resolver(_ScriptedProvider(_revoked()))
    assert resolver.is_covered(LicenseStatus.VALID, _LICENSE) is False


def test_online_active_but_offline_expired_is_not_covered():
    # Offline signature/expiry is still enforced — online cannot resurrect it.
    resolver = _resolver(_ScriptedProvider(_active()))
    assert resolver.is_covered(LicenseStatus.EXPIRED, _LICENSE) is False


# --- fail-soft on authority outage -----------------------------------------


def test_unreachable_within_licence_grace_holds_coverage():
    # No prior verdict + authority down → fall back to offline-only (do NOT brick).
    resolver = _resolver(_ScriptedProvider(_unreachable()))
    assert resolver.is_covered(LicenseStatus.VALID, _LICENSE) is True
    assert resolver.is_covered(LicenseStatus.GRACE, _LICENSE) is True


def test_unreachable_past_licence_grace_degrades():
    resolver = _resolver(_ScriptedProvider(_unreachable()))
    assert resolver.is_covered(LicenseStatus.EXPIRED, _LICENSE) is False


def test_last_good_active_is_held_during_outage():
    # active (reachable) then the authority goes dark → keep honouring active.
    provider = _ScriptedProvider(_active(), _unreachable())
    clock_time = [_NOW]
    resolver = _resolver(provider, clock=lambda: clock_time[0], cache_ttl_seconds=60)
    assert resolver.is_covered(LicenseStatus.VALID, _LICENSE) is True
    clock_time[0] = _NOW + timedelta(seconds=120)  # past TTL → re-hit, now down
    assert resolver.is_covered(LicenseStatus.VALID, _LICENSE) is True


def test_last_good_negative_is_held_during_outage():
    # inactive (reachable) then dark → do NOT re-open coverage during the outage.
    provider = _ScriptedProvider(_inactive(), _unreachable())
    clock_time = [_NOW]
    resolver = _resolver(provider, clock=lambda: clock_time[0], cache_ttl_seconds=60)
    assert resolver.is_covered(LicenseStatus.VALID, _LICENSE) is False
    clock_time[0] = _NOW + timedelta(seconds=120)  # past TTL → re-hit, now down
    assert resolver.is_covered(LicenseStatus.VALID, _LICENSE) is False


# --- caching ----------------------------------------------------------------


def test_second_call_within_ttl_does_not_rehit_provider():
    provider = _ScriptedProvider(_active())
    resolver = _resolver(provider, cache_ttl_seconds=300)
    resolver.is_covered(LicenseStatus.VALID, _LICENSE)
    resolver.is_covered(LicenseStatus.VALID, _LICENSE)
    assert provider.call_count == 1


def test_call_after_ttl_refreshes_from_provider():
    provider = _ScriptedProvider(_active(), _inactive())
    clock_time = [_NOW]
    resolver = _resolver(provider, clock=lambda: clock_time[0], cache_ttl_seconds=60)
    assert resolver.is_covered(LicenseStatus.VALID, _LICENSE) is True
    clock_time[0] = _NOW + timedelta(seconds=120)
    assert resolver.is_covered(LicenseStatus.VALID, _LICENSE) is False
    assert provider.call_count == 2
