"""HMAC-SHA256 signing for outbound webhook deliveries (core, agnostic).

The signature is computed over the *exact* raw JSON body bytes that are sent,
using the subscription's secret. Subscribers verify by recomputing the same
HMAC over the received body and constant-time comparing it to the
``X-VBWD-Signature`` header.
"""
from __future__ import annotations

import hashlib
import hmac

# Header names sent on every outbound POST.
SIGNATURE_HEADER = "X-VBWD-Signature"
EVENT_HEADER = "X-VBWD-Event"
DELIVERY_ID_HEADER = "X-VBWD-Delivery-Id"
TIMESTAMP_HEADER = "X-VBWD-Timestamp"

# The ``X-VBWD-Signature`` value is prefixed with the algorithm name.
SIGNATURE_PREFIX = "sha256="


def compute_signature(secret: str, body: bytes) -> str:
    """Return the ``sha256=<hexdigest>`` signature for ``body``.

    Args:
        secret: The subscription's signing secret.
        body: The exact request body bytes that will be transmitted.
    """
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: str, body: bytes, provided_signature: str) -> bool:
    """Constant-time check that ``provided_signature`` matches ``body``.

    Provided here for completeness/tests; production subscribers run the same
    comparison on their side (see ``docs/architecture/webhooks.md``).
    """
    expected = compute_signature(secret, body)
    return hmac.compare_digest(expected, provided_signature or "")
