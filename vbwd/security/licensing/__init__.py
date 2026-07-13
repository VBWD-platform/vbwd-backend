"""Client-side license gate (S135-CLIENT) — verify a set of signed keys offline.

Core-agnostic cross-cutting infrastructure (the same species as ``route_audit``
and the auth/permission markers): it verifies signed keys, exposes the resolved
entitlements, and enforces a request-level marker. It names ZERO products,
plugins, or features — scopes/features arrive from signed keys and the
plugin-fed ``licensed_feature_registry``. The signing authority (policy) is out
of core (S135-SERVER).
"""
from vbwd.security.licensing.decorator import (
    LICENSED_FEATURE_MARKER,
    REQUIRES_LICENSE_MARKER,
    requires_license,
)
from vbwd.security.licensing.license_context import (
    LicenseContext,
    LicenseNotConfigured,
    NullLicenseContext,
)
from vbwd.security.licensing.license_key import (
    LicenseKey,
    LicenseStatus,
)
from vbwd.security.licensing.license_store import (
    LicenseKeyRejected,
    LicenseStore,
)
from vbwd.security.licensing.loader import (
    LicenseEnvironment,
    build_license_environment,
)
from vbwd.security.licensing.ports import (
    ILicenseActivationClient,
    ISignatureVerifier,
    LicenseActivationError,
)
from vbwd.security.licensing.verifier import LicenseVerifier

__all__ = [
    "requires_license",
    "REQUIRES_LICENSE_MARKER",
    "LICENSED_FEATURE_MARKER",
    "LicenseContext",
    "NullLicenseContext",
    "LicenseNotConfigured",
    "LicenseKey",
    "LicenseStatus",
    "LicenseStore",
    "LicenseKeyRejected",
    "LicenseVerifier",
    "LicenseEnvironment",
    "build_license_environment",
    "ISignatureVerifier",
    "ILicenseActivationClient",
    "LicenseActivationError",
]
