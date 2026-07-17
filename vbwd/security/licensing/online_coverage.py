"""Effective-coverage resolver (S144.3) — combine offline AND online, fail-soft.

Effective coverage = the offline signature/expiry result (S135) **AND** the
authority's live verdict (the online status channel). This module owns the ONE
combination rule (DRY):

- online ``active``/``unknown`` → no override; defer to the offline result.
- online ``inactive``/``revoked`` → NOT covered, even if the signature is valid
  (online status wins over a still-valid signature).
- authority unreachable → **fail-soft**: hold the last authoritative verdict if
  we have one (so a revocation is not forgotten during an outage), otherwise fall
  back to the offline result. The licence's own grace window (an offline
  ``GRACE`` status) keeps a paying customer covered through an authority outage —
  never a hard brick.

The last authoritative verdict is cached with a TTL so repeated coverage checks
do not hammer the authority; after the TTL it refreshes. The ``clock`` is
injected (no inline ``datetime.now()``); the provider is a port (fake in tests).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict

from vbwd.security.licensing.license_key import LicenseStatus
from vbwd.security.licensing.ports import (
    AuthorityStatus,
    ILicenseStatusProvider,
    LicenseAuthorityStatus,
)

DEFAULT_CACHE_TTL_SECONDS = 300

# Offline statuses under which a held key still grants what it claims (mirrors
# LicenseContext's covering set — the offline half of effective coverage).
_OFFLINE_COVERING_STATUSES = (LicenseStatus.VALID, LicenseStatus.GRACE)

# Online verdicts that override a valid signature and revoke coverage.
_NEGATIVE_STATUSES = (AuthorityStatus.INACTIVE, AuthorityStatus.REVOKED)


@dataclass(frozen=True)
class _CacheEntry:
    result: LicenseAuthorityStatus
    stored_at: datetime


class OnlineCoverageResolver:
    """Resolves effective coverage (offline AND online) with cache + fail-soft."""

    def __init__(
        self,
        status_provider: ILicenseStatusProvider,
        clock: Callable[[], datetime],
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._status_provider = status_provider
        self._clock = clock
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache: Dict[str, _CacheEntry] = {}

    def is_covered(self, offline_status: LicenseStatus, license_number: str) -> bool:
        """Whether ``license_number`` is covered by BOTH offline and online."""
        offline_covers = offline_status in _OFFLINE_COVERING_STATUSES
        answer = self._authoritative_answer(license_number)
        if answer.reachable and answer.status in _NEGATIVE_STATUSES:
            return False
        return offline_covers

    def _authoritative_answer(self, license_number: str) -> LicenseAuthorityStatus:
        """The current verdict — cached within TTL, else refreshed; fail-soft."""
        now = self._clock()
        cached = self._cache.get(license_number)
        if cached is not None and now - cached.stored_at < self._cache_ttl:
            return cached.result

        fresh = self._status_provider.status(license_number)
        if fresh.reachable:
            self._cache[license_number] = _CacheEntry(result=fresh, stored_at=now)
            return fresh

        # Unreachable: hold the last authoritative verdict if we have one so a
        # revocation is not forgotten during the outage; else report unreachable
        # and let ``is_covered`` fall back to the offline result (do NOT brick).
        return cached.result if cached is not None else fresh
