"""Build the license environment from config at boot.

Turns the app config (safe defaults, ops-tunable) into the objects the app
stashes: the request-scoped context, the key store, the activation client, and
the degraded flag. Collaborators (signature verifier, clock, feature registry,
activation client) are injectable so the boot path is unit-testable with a
fixture keypair — no real key needed.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional, Union

from vbwd.security.licensing.instance_fingerprint import resolve_instance_fingerprint
from vbwd.security.licensing.license_context import (
    LicenseContext,
    NullLicenseContext,
)
from vbwd.security.licensing.license_store import LicenseStore
from vbwd.security.licensing.ports import (
    ILicenseActivationClient,
    ILicenseStatusProvider,
    ISignatureVerifier,
)
from vbwd.security.licensing.status_provider import (
    HttpLicenseStatusProvider,
    NullLicenseStatusProvider,
)
from vbwd.security.licensing.verifier import LicenseVerifier

# Ops-tunable config keys + safe defaults (sprint §2.6). CE never enforces, so
# LICENSE_REQUIRED defaults false and a clean ``git clone`` boots fully open.
CONFIG_REQUIRED = "LICENSE_REQUIRED"
CONFIG_KEYS_DIR = "LICENSE_KEYS_DIR"
CONFIG_PUBLIC_KEY = "LICENSE_PUBLIC_KEY"
CONFIG_GRACE_DAYS = "LICENSE_GRACE_DAYS"
CONFIG_HUB_URL = "VBWD_LICENSE_HUB_URL"
CONFIG_INSTANCE_ID = "LICENSE_INSTANCE_ID"
CONFIG_SIGNATURE_VERIFIER = "LICENSE_SIGNATURE_VERIFIER"
CONFIG_ACTIVATION_CLIENT = "LICENSE_ACTIVATION_CLIENT"
# S144.3: the online verify channel. No URL ⇒ NullLicenseStatusProvider ⇒
# offline-only, exactly as S135 today (the critical no-regression case).
CONFIG_AUTHORITY_URL = "VBWD_LICENSE_AUTHORITY_URL"

DEFAULT_KEYS_DIR = os.path.join("var", "license", "keys")
DEFAULT_GRACE_DAYS = 14

AnyLicenseContext = Union[LicenseContext, NullLicenseContext]


class _RejectingSignatureVerifier(ISignatureVerifier):
    """Trusts nothing — used when enforcement is required but no key is pinned.

    Keeps a misconfigured ``LICENSE_REQUIRED=true`` build in degraded mode
    (every key ``INVALID_SIGNATURE``) rather than silently open.
    """

    def verify(self, message: bytes, signature: bytes) -> bool:
        return False


@dataclass(frozen=True)
class LicenseEnvironment:
    """The boot-time license objects the app stashes and wires onto requests."""

    context: AnyLicenseContext
    store: Optional[LicenseStore]
    activation_client: Optional[ILicenseActivationClient]
    status_provider: ILicenseStatusProvider
    instance_id: str
    required: bool
    degraded: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _keys_present(keys_dir: str) -> bool:
    if not os.path.isdir(keys_dir):
        return False
    return any(name.endswith(".vbwd") for name in os.listdir(keys_dir))


def _resolve_signature_verifier(
    config, signature_verifier: Optional[ISignatureVerifier]
) -> Optional[ISignatureVerifier]:
    """Prefer an injected verifier, else build Ed25519 from the pinned key."""
    injected = signature_verifier or config.get(CONFIG_SIGNATURE_VERIFIER)
    if injected is not None:
        return injected
    public_key = config.get(CONFIG_PUBLIC_KEY)
    if public_key:
        from vbwd.security.licensing.signature_verifier import (
            Ed25519SignatureVerifier,
        )

        return Ed25519SignatureVerifier.from_base64url(public_key)
    return None


def _resolve_instance_id(config, keys_dir: str) -> str:
    """This instance's fingerprint — config override, else host+salt hash."""
    override = config.get(CONFIG_INSTANCE_ID)
    if override:
        return override
    database_url = config.get("SQLALCHEMY_DATABASE_URI") or ""
    salt_dir = os.path.dirname(keys_dir) or keys_dir
    return resolve_instance_fingerprint(database_url, salt_dir)


def _resolve_activation_client(
    config, activation_client: Optional[ILicenseActivationClient]
) -> Optional[ILicenseActivationClient]:
    injected = activation_client or config.get(CONFIG_ACTIVATION_CLIENT)
    if injected is not None:
        return injected
    hub_url = config.get(CONFIG_HUB_URL)
    if hub_url:
        from vbwd.security.licensing.activation_client import (
            HttpLicenseActivationClient,
        )

        return HttpLicenseActivationClient(hub_url)
    return None


def _resolve_status_provider(
    config, status_provider: Optional[ILicenseStatusProvider]
) -> ILicenseStatusProvider:
    """The online verify channel — HTTP when a URL is set, else the null default.

    With no authority URL the null provider reports "not configured"
    (unreachable), so effective coverage is offline-only — S135 unchanged.
    """
    if status_provider is not None:
        return status_provider
    authority_url = config.get(CONFIG_AUTHORITY_URL)
    if authority_url:
        return HttpLicenseStatusProvider(authority_url)
    return NullLicenseStatusProvider()


def build_license_environment(
    config,
    *,
    signature_verifier: Optional[ISignatureVerifier] = None,
    activation_client: Optional[ILicenseActivationClient] = None,
    status_provider: Optional[ILicenseStatusProvider] = None,
    clock: Optional[Callable[[], datetime]] = None,
    feature_registry: Optional[Callable[[], List[str]]] = None,
) -> LicenseEnvironment:
    """Assemble the license environment from ``config`` + injected collaborators.

    ``config`` is anything with a ``.get(key, default)`` (a Flask ``app.config``
    or a plain dict).
    """
    required = bool(config.get(CONFIG_REQUIRED, False))
    keys_dir = config.get(CONFIG_KEYS_DIR) or DEFAULT_KEYS_DIR
    grace_fallback = int(config.get(CONFIG_GRACE_DAYS, DEFAULT_GRACE_DAYS))
    resolved_clock = clock or _utc_now

    verifier_impl = _resolve_signature_verifier(config, signature_verifier)
    instance_id = _resolve_instance_id(config, keys_dir)
    client = _resolve_activation_client(config, activation_client)
    provider = _resolve_status_provider(config, status_provider)

    context: AnyLicenseContext
    store: Optional[LicenseStore]

    if verifier_impl is not None:
        store = LicenseStore(
            keys_dir,
            LicenseVerifier(verifier_impl, instance_id, resolved_clock, grace_fallback),
        )
        context = LicenseContext(store, feature_registry)
    elif required or _keys_present(keys_dir):
        # Enforcing (or holding keys) but no trustable verifier → degraded,
        # never silently open.
        store = LicenseStore(
            keys_dir,
            LicenseVerifier(
                _RejectingSignatureVerifier(),
                instance_id,
                resolved_clock,
                grace_fallback,
            ),
        )
        context = LicenseContext(store, feature_registry)
    else:
        # Fully open CE: nothing to verify and nothing required.
        store = None
        context = NullLicenseContext()

    degraded = required and not context.is_active()
    return LicenseEnvironment(
        context=context,
        store=store,
        activation_client=client,
        status_provider=provider,
        instance_id=instance_id,
        required=required,
        degraded=degraded,
    )
