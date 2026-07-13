"""The production Ed25519 verifier accepts genuine signatures, rejects forgeries.

Runs against real libsodium (PyNaCl) when installed; skips otherwise so the
suite stays green on a bare host (the fixture-verifier tests cover the logic).
"""
import pytest

from vbwd.security.licensing.license_key import base64url_encode
from vbwd.security.licensing.signature_verifier import Ed25519SignatureVerifier

nacl_signing = pytest.importorskip("nacl.signing")


def test_valid_signature_verifies():
    signing_key = nacl_signing.SigningKey.generate()
    message = b"the-signed-payload"
    signature = signing_key.sign(message).signature

    verifier = Ed25519SignatureVerifier(bytes(signing_key.verify_key))
    assert verifier.verify(message, signature) is True


def test_tampered_message_is_rejected():
    signing_key = nacl_signing.SigningKey.generate()
    signature = signing_key.sign(b"original").signature

    verifier = Ed25519SignatureVerifier(bytes(signing_key.verify_key))
    assert verifier.verify(b"tampered", signature) is False


def test_from_base64url_public_key():
    signing_key = nacl_signing.SigningKey.generate()
    message = b"payload"
    signature = signing_key.sign(message).signature

    public_key_b64 = base64url_encode(bytes(signing_key.verify_key))
    verifier = Ed25519SignatureVerifier.from_base64url(public_key_b64)
    assert verifier.verify(message, signature) is True
