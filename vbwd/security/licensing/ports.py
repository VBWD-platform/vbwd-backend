"""Ports for the license gate (DIP).

The client depends on these narrow abstractions, never on a concrete crypto
library or HTTP client. The production signature verifier wraps Ed25519
(libsodium / PyNaCl); tests inject a fixture verifier. The activation client
talks to the license hub; tests inject a fake.
"""
from abc import ABC, abstractmethod


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
