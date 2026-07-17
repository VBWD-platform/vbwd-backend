"""Production signature verifier — Ed25519 via libsodium (PyNaCl).

Wraps the vetted primitive behind :class:`ISignatureVerifier` (DIP) so the
algorithm is swappable and tests inject a fixture instead. The client holds only
the PUBLIC key: it can verify, never mint. PyNaCl is imported lazily so an
instance that does not enforce licensing (the CE default) boots without the
dependency being exercised.
"""
from vbwd.security.licensing.license_key import base64url_decode
from vbwd.security.licensing.ports import ISignatureVerifier


class Ed25519SignatureVerifier(ISignatureVerifier):
    """Verifies detached Ed25519 signatures against a pinned public key."""

    def __init__(self, public_key: bytes) -> None:
        from nacl.signing import VerifyKey

        self._verify_key = VerifyKey(public_key)

    @classmethod
    def from_base64url(cls, public_key_b64: str) -> "Ed25519SignatureVerifier":
        """Build from a base64url-encoded 32-byte public key (config value)."""
        return cls(base64url_decode(public_key_b64))

    def verify(self, message: bytes, signature: bytes) -> bool:
        from nacl.exceptions import BadSignatureError

        try:
            self._verify_key.verify(message, signature)
            return True
        except (BadSignatureError, ValueError):
            return False
