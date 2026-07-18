"""The collection of held license keys, persisted as files in the keys dir.

A "license" is a *set* of independently-signed, scoped key files
(``<key_id>.vbwd``): an optional platform key plus zero-or-more per-plugin keys.
The store loads and re-verifies them on read (so a key that has since expired
reports ``EXPIRED`` without a rewrite), adds a new one after verifying it, and
removes one by id. One expired key never invalidates the others.
"""
import os
from typing import List, Optional, Tuple

from vbwd.security.licensing.license_key import LicenseKey, LicenseStatus
from vbwd.security.licensing.verifier import LicenseVerifier

KEY_FILE_SUFFIX = ".vbwd"


def read_held_envelope(keys_dir: str) -> Optional[str]:
    """The box's own raw identity envelope — the first held key file, unverified.

    A box presents this to the licence broker as proof it is a known instance;
    the broker (not the box) re-verifies the Ed25519 signature. Reads the raw
    envelope string of the first key file in ``keys_dir`` (a merchant holds a
    single covering licence), or ``None`` when none is held. No verification and
    no parse here — it is the raw wire envelope, read exactly as the store reads
    it (shares ``KEY_FILE_SUFFIX``, DRY).
    """
    if not os.path.isdir(keys_dir):
        return None
    for filename in sorted(os.listdir(keys_dir)):
        if filename.endswith(KEY_FILE_SUFFIX):
            with open(os.path.join(keys_dir, filename), encoding="utf-8") as handle:
                return handle.read().strip()
    return None


# Statuses that a key must NOT have to be accepted into the store on add.
_REJECTED_ON_ADD = (
    LicenseStatus.INVALID_SIGNATURE,
    LicenseStatus.WRONG_INSTANCE,
    LicenseStatus.EXPIRED,
    LicenseStatus.MISSING,
)


class LicenseKeyRejected(ValueError):
    """Raised by :meth:`LicenseStore.add` when an envelope fails verification."""

    def __init__(self, status: LicenseStatus) -> None:
        super().__init__(f"License key rejected: {status.value}")
        self.status = status


class LicenseStore:
    """Loads/holds/persists the collection of verified key files."""

    def __init__(self, keys_dir: str, verifier: LicenseVerifier) -> None:
        self._keys_dir = keys_dir
        self._verifier = verifier

    def all(self) -> List[Tuple[LicenseKey, LicenseStatus]]:
        """Every stored key with its current status (re-verified on read)."""
        results: List[Tuple[LicenseKey, LicenseStatus]] = []
        if not os.path.isdir(self._keys_dir):
            return results
        for filename in sorted(os.listdir(self._keys_dir)):
            if not filename.endswith(KEY_FILE_SUFFIX):
                continue
            envelope = self._read(filename)
            key, status = self._verifier.verify(envelope)
            if key is not None:
                results.append((key, status))
        return results

    def add(self, raw_envelope: str) -> Tuple[LicenseKey, LicenseStatus]:
        """Verify then persist an envelope. Raises :class:`LicenseKeyRejected`."""
        key, status = self._verifier.verify(raw_envelope)
        if key is None or status in _REJECTED_ON_ADD:
            raise LicenseKeyRejected(status)
        os.makedirs(self._keys_dir, exist_ok=True)
        with open(self._key_path(key.key_id), "w", encoding="utf-8") as handle:
            handle.write(raw_envelope)
        return key, status

    def remove(self, key_id: str) -> bool:
        """Delete the key file for ``key_id``. Returns True if it existed."""
        path = self._key_path(key_id)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def _key_path(self, key_id: str) -> str:
        return os.path.join(self._keys_dir, f"{key_id}{KEY_FILE_SUFFIX}")

    def _read(self, filename: str) -> str:
        with open(os.path.join(self._keys_dir, filename), encoding="utf-8") as handle:
            return handle.read().strip()
