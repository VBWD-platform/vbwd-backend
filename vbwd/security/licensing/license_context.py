"""The app-facing view of the held license set, resolved once per request.

``LicenseContext`` answers the questions the rest of the app asks — is a feature
covered, is the license active, is a seat count within limit — by resolving
whichever held key's scope covers the request. It is a pure function over the
store's current key set (multi-key precedence in ONE place, DRY): a key is
*covering* iff its status is VALID or GRACE and its scope includes the feature.

``NullLicenseContext`` is the Liskov-safe stand-in for the not-required / not-
configured path: every question answers "allowed" so callers never branch on
``None``.
"""
from typing import Callable, Dict, List, Optional, Tuple

from vbwd.security.licensing.license_key import LicenseKey, LicenseStatus
from vbwd.security.licensing.license_store import LicenseStore

# The statuses under which a held key still grants what it claims.
_COVERING_STATUSES = (LicenseStatus.VALID, LicenseStatus.GRACE)

SEATS_RESOURCE = "seats"


class LicenseNotConfigured(RuntimeError):
    """Raised when a key op is attempted with no verifiable store (open CE)."""


class LicenseContext:
    """Resolves entitlements from the held key set."""

    def __init__(
        self,
        store: LicenseStore,
        feature_registry: Optional[Callable[[], List[str]]] = None,
    ) -> None:
        self._store = store
        self._feature_registry = feature_registry

    # --- entitlement questions -------------------------------------------

    def has_feature(self, feature: str) -> bool:
        """Whether any covering key's scope grants ``feature``."""
        return any(key.covers(feature) for key in self._covering_keys())

    def is_active(self) -> bool:
        """Whether at least one held key is currently VALID or GRACE."""
        return bool(self._covering_keys())

    def within_seat_limit(self, count: int) -> bool:
        """Whether ``count`` seats is within the platform key's limit.

        With no covering platform (wildcard) key the seat limit is unenforced.
        """
        platform_key = self._platform_key()
        if platform_key is None:
            return True
        return count <= platform_key.seat_limit

    def resource_usage(self) -> List[Dict[str, object]]:
        """Resource limits for the License tab (extensible; seats today)."""
        platform_key = self._platform_key()
        return [
            {
                "resource": SEATS_RESOURCE,
                "limit": platform_key.seat_limit if platform_key else None,
                "used": None,
            }
        ]

    def declared_features(self) -> List[Dict[str, object]]:
        """Each licensable feature the registry declares + whether it is covered."""
        if self._feature_registry is None:
            return []
        return [
            {"feature": feature, "licensed": self.has_feature(feature)}
            for feature in self._feature_registry()
        ]

    # --- key management (delegates to the store) -------------------------

    def add_key(self, raw_envelope: str) -> Tuple[LicenseKey, LicenseStatus]:
        """Verify and persist a new key envelope."""
        return self._store.add(raw_envelope)

    def remove_key(self, key_id: str) -> bool:
        """Remove a held key by id."""
        return self._store.remove(key_id)

    def status_payload(self) -> Dict[str, object]:
        """The full status body served by ``GET /api/v1/admin/license``."""
        keys = self._store.all()
        platform_key = self._platform_key()
        return {
            "configured": True,
            "active": self.is_active(),
            "edition": platform_key.edition if platform_key else None,
            "seats": {
                "used": None,
                "limit": platform_key.seat_limit if platform_key else None,
            },
            "resources": self.resource_usage(),
            "features": self.declared_features(),
            "keys": [_key_row(key, status) for key, status in keys],
        }

    # --- internals -------------------------------------------------------

    def _covering_keys(self) -> List[LicenseKey]:
        return [
            key for key, status in self._store.all() if status in _COVERING_STATUSES
        ]

    def _platform_key(self) -> Optional[LicenseKey]:
        for key in self._covering_keys():
            if key.is_platform_scope:
                return key
        return None


class NullLicenseContext:
    """Open-path context: nothing is enforced (Liskov-safe stand-in)."""

    def has_feature(self, feature: str) -> bool:
        return True

    def is_active(self) -> bool:
        return True

    def within_seat_limit(self, count: int) -> bool:
        return True

    def resource_usage(self) -> List[Dict[str, object]]:
        return []

    def declared_features(self) -> List[Dict[str, object]]:
        return []

    def add_key(self, raw_envelope: str) -> Tuple[LicenseKey, LicenseStatus]:
        raise LicenseNotConfigured(
            "Licensing is not configured on this instance; no public key to verify against."
        )

    def remove_key(self, key_id: str) -> bool:
        raise LicenseNotConfigured("Licensing is not configured on this instance.")

    def status_payload(self) -> Dict[str, object]:
        return {
            "configured": False,
            "active": True,
            "edition": None,
            "seats": {"used": None, "limit": None},
            "resources": [],
            "features": [],
            "keys": [],
        }


def _key_row(key: LicenseKey, status: LicenseStatus) -> Dict[str, object]:
    """The per-key table row the License tab renders."""
    return {
        "key_id": key.key_id,
        "scope": list(key.scope),
        "status": status.value,
        "customer": key.customer,
        "edition": key.edition,
        "expires_at": key.expires_at.isoformat(),
        "seat_limit": key.seat_limit,
    }
