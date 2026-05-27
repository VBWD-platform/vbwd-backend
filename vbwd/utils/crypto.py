"""Symmetric encryption helpers — one home for the cipher (§5 DRY).

Provides:

* ``TokenCipher`` — thin wrapper around ``cryptography.fernet.Fernet``.
* ``EncryptedString`` — a SQLAlchemy ``TypeDecorator`` that transparently
  encrypts strings on write and decrypts on read. Use this for any
  column holding a secret-shaped value (OAuth tokens, deploy tokens,
  third-party API keys persisted per-tenant). Stored type is ``Text``,
  so no schema migration is needed when retro-fitting an existing column.

The cipher key is resolved per-app: production reads
``VBWD_TOKEN_ENCRYPTION_KEY`` from env (required-form via compose,
see ``docker-compose.server.yaml``). Dev / test environments fall
back to a deterministic key derived from ``FLASK_SECRET_KEY`` so the
suite runs out-of-the-box without manual setup. Either way the key
never leaves the cipher instance.
"""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import Text, TypeDecorator


def _derive_dev_key(seed: str) -> bytes:
    """Deterministic Fernet key from any seed string.

    Used in dev/test only — production must set
    ``VBWD_TOKEN_ENCRYPTION_KEY`` explicitly so rotation is possible.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    # Fernet keys are 32 bytes, url-safe base64 encoded (44 chars).
    return base64.urlsafe_b64encode(digest)


class TokenCipher:
    """Fernet-backed symmetric cipher for at-rest token encryption."""

    def __init__(self, key: bytes) -> None:
        # raises ValueError if the key is malformed — fail fast.
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a UTF-8 string; return base64 ciphertext."""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """Reverse of :meth:`encrypt`; raises ``InvalidToken`` on tamper/key mismatch."""
        return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")


_cached_cipher: Optional[TokenCipher] = None
_cached_key: Optional[bytes] = None


def get_default_cipher() -> TokenCipher:
    """Resolve the process-wide cipher; cached on first call.

    Resolution order:
      1. ``VBWD_TOKEN_ENCRYPTION_KEY`` env var (Fernet key, url-safe base64).
      2. Derived from ``FLASK_SECRET_KEY`` env var (dev/test convenience).
      3. Derived from a known constant ``"vbwd-test-seed"`` (last-resort
         fallback for the unit-test environment where neither is set).

    The cache is keyed on the actual resolved key bytes, so changing the
    env in a long-running process is picked up automatically.
    """
    global _cached_cipher, _cached_key

    raw_key = os.environ.get("VBWD_TOKEN_ENCRYPTION_KEY")
    if raw_key:
        key_bytes = raw_key.encode("ascii")
    else:
        seed = os.environ.get("FLASK_SECRET_KEY") or "vbwd-test-seed"
        key_bytes = _derive_dev_key(seed)

    if _cached_cipher is None or _cached_key != key_bytes:
        _cached_cipher = TokenCipher(key_bytes)
        _cached_key = key_bytes
    return _cached_cipher


def reset_default_cipher_cache() -> None:
    """Test hook: forget the cached cipher so a different key is picked up."""
    global _cached_cipher, _cached_key
    _cached_cipher = None
    _cached_key = None


class EncryptedString(TypeDecorator):
    """SQLAlchemy column type that encrypts on write, decrypts on read.

    Stored as ``Text`` (no schema migration to swap an existing
    ``db.Text`` column over). ``None`` round-trips as ``None`` so
    nullable columns keep working.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"EncryptedString expected str, got {type(value).__name__}")
        return get_default_cipher().encrypt(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return get_default_cipher().decrypt(value)
        except InvalidToken:
            # Legacy plaintext row — return as-is so operator rotation
            # scripts can re-encrypt without losing data. Logged below.
            import logging

            logging.getLogger(__name__).warning(
                "EncryptedString: decrypt failed for a stored value; "
                "treating it as legacy plaintext. Run the rotation "
                "script to re-encrypt."
            )
            return value
