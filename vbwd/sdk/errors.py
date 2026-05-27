"""SDK adapter exception types.

``UnsupportedOperationError`` signals that an adapter structurally cannot
perform an operation (e.g. Mercado Pago does not support deferred
``capture_payment`` — captures happen on user redirect). Raising rather
than returning ``SDKResponse(success=False)`` keeps the
``ISDKAdapter`` Liskov contract honest: a successful return means "I
performed the op"; a failed return means "I tried but the provider said
no"; an exception means "this provider does not implement this op".
"""


class UnsupportedOperationError(Exception):
    """Raised by SDK adapters for structurally-unsupported operations.

    Callers (e.g. ``CaptureService``) catch this and translate it to a
    domain-appropriate failure (typically HTTP 501 at the route layer).
    """
