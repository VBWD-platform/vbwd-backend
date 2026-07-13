"""Soft instance fingerprint.

Binds a key to *this* box so copying a key file to a second machine fails
verification, while a legitimate backup/restore or migration survives (the
inputs are the DB host + a persisted random salt, NOT hardware ids). A cloned
box simply re-activates its code — no hard brick (see sprint §9.4).
"""
import hashlib
import os
import secrets
from urllib.parse import urlsplit

# The salt file lives under the license var dir so it survives restarts but is
# per-instance (a fresh clone gets its own salt on first boot).
SALT_FILENAME = ".salt"


def compute_instance_fingerprint(database_host: str, salt: str) -> str:
    """Deterministic fingerprint from the DB host and a persisted salt.

    Pure: identical ``(database_host, salt)`` always yields the same value; a
    different salt yields a different value.
    """
    digest_source = f"{database_host}:{salt}".encode("utf-8")
    return hashlib.sha256(digest_source).hexdigest()


def database_host_from_url(database_url: str) -> str:
    """Extract the host component of a SQLAlchemy/DB URL (empty if none)."""
    return urlsplit(database_url).hostname or ""


def load_or_create_salt(salt_dir: str) -> str:
    """Read the persisted salt from ``salt_dir``, creating one if absent."""
    salt_path = os.path.join(salt_dir, SALT_FILENAME)
    if os.path.exists(salt_path):
        with open(salt_path, encoding="utf-8") as handle:
            existing = handle.read().strip()
        if existing:
            return existing

    os.makedirs(salt_dir, exist_ok=True)
    salt = secrets.token_hex(16)
    with open(salt_path, "w", encoding="utf-8") as handle:
        handle.write(salt)
    return salt


def resolve_instance_fingerprint(database_url: str, salt_dir: str) -> str:
    """Compute this instance's fingerprint from its DB host + persisted salt."""
    return compute_instance_fingerprint(
        database_host_from_url(database_url), load_or_create_salt(salt_dir)
    )
