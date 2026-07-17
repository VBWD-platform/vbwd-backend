"""Ports for the license gate (DIP).

The client depends on these narrow abstractions, never on a concrete crypto
library or HTTP client. The production signature verifier wraps Ed25519
(libsodium / PyNaCl); tests inject a fixture verifier. The activation client
talks to the license hub; tests inject a fake.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class ISignatureVerifier(ABC):
    """Verifies a detached signature over a message.

    The client holds only the public half — it can verify but never mint.
    Implementations MUST be pure functions of ``(message, signature)``.
    """

    @abstractmethod
    def verify(self, message: bytes, signature: bytes) -> bool:
        """Return True iff ``signature`` is a valid signature over ``message``."""
        raise NotImplementedError


class ILicenseActivationClient(ABC):
    """Redeems a dashboard code against the hub for an instance-bound envelope."""

    @abstractmethod
    def activate(self, code: str, instance_id: str) -> str:
        """Exchange ``code`` (+ this instance's fingerprint) for a signed envelope.

        Raises :class:`LicenseActivationError` on any transport/hub failure.
        """
        raise NotImplementedError


class LicenseActivationError(RuntimeError):
    """Raised when a code activation against the hub fails."""


class AuthorityStatus(Enum):
    """The licence authority's live verdict for one licence (S144.3).

    ``UNKNOWN`` is used both for an authority that does not recognise the licence
    and — with ``reachable=False`` — for the "no authoritative answer" case (no
    authority configured, or the authority is unreachable).
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LicenseAuthorityStatus:
    """The result of asking the authority whether a licence is still live.

    ``reachable`` says whether ``status`` is an authoritative answer: ``False``
    means we could not reach the authority (network error / no URL configured),
    so the caller must fall into the fail-soft path rather than trust ``status``.
    """

    status: AuthorityStatus
    checked_at: Optional[datetime]
    reachable: bool


class ILicenseStatusProvider(ABC):
    """Answers "is licence X live right now?" against the authority (read-only).

    The verify endpoint needs no API key (a consuming instance merely *holds* a
    licence). Implementations MUST NOT raise on a transport failure — they return
    ``reachable=False`` so the resolver can apply the fail-soft/grace policy.
    """

    @abstractmethod
    def status(self, license_number: str) -> LicenseAuthorityStatus:
        """Return the authority's current verdict for ``license_number``."""
        raise NotImplementedError
