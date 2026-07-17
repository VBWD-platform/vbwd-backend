"""Pure verification of a single signed license envelope.

``LicenseVerifier`` classifies one envelope into ``(LicenseKey | None,
LicenseStatus)``. It is a pure function of its injected collaborators — the
signature verifier (crypto behind a port), this instance's fingerprint, and an
injected ``clock`` (no inline ``datetime.now()``). It performs no I/O; the store
handles files.
"""
from datetime import datetime, timedelta
from typing import Callable, Optional, Tuple

from vbwd.security.licensing.license_key import (
    LicenseKey,
    LicenseStatus,
    decode_license_payload,
    split_envelope,
)
from vbwd.security.licensing.ports import ISignatureVerifier


class LicenseVerifier:
    """Verifies a single envelope's signature, instance binding, and expiry."""

    def __init__(
        self,
        signature_verifier: ISignatureVerifier,
        instance_fingerprint: str,
        clock: Callable[[], datetime],
        grace_days_fallback: int = 0,
    ) -> None:
        self._signature_verifier = signature_verifier
        self._instance_fingerprint = instance_fingerprint
        self._clock = clock
        self._grace_days_fallback = grace_days_fallback

    def verify(
        self, envelope: Optional[str]
    ) -> Tuple[Optional[LicenseKey], LicenseStatus]:
        """Classify ``envelope`` into its key and status.

        A missing/empty envelope is ``MISSING``. A structurally broken envelope,
        a failed signature, or an undecodable payload is ``INVALID_SIGNATURE``
        (no trusted key is returned). Once the signature is trusted the key is
        returned alongside ``WRONG_INSTANCE`` / ``VALID`` / ``GRACE`` /
        ``EXPIRED``.
        """
        if not envelope:
            return None, LicenseStatus.MISSING

        try:
            payload_bytes, signature_bytes = split_envelope(envelope)
        except (ValueError, TypeError):
            return None, LicenseStatus.INVALID_SIGNATURE

        if not self._signature_verifier.verify(payload_bytes, signature_bytes):
            return None, LicenseStatus.INVALID_SIGNATURE

        try:
            key = decode_license_payload(payload_bytes, self._grace_days_fallback)
        except (ValueError, KeyError, TypeError):
            return None, LicenseStatus.INVALID_SIGNATURE

        if key.instance_id != self._instance_fingerprint:
            return key, LicenseStatus.WRONG_INSTANCE

        now = self._clock()
        if now < key.expires_at:
            return key, LicenseStatus.VALID

        grace_end = key.expires_at + timedelta(days=key.grace_days)
        if now < grace_end:
            return key, LicenseStatus.GRACE

        return key, LicenseStatus.EXPIRED
