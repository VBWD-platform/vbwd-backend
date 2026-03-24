"""Mock SDK adapter for testing."""
import uuid
from decimal import Decimal
from typing import Dict, Any, Optional, List

from vbwd.sdk.interface import ISDKAdapter, SDKResponse


class MockSDKAdapter(ISDKAdapter):
    """Mock payment adapter for testing.

    Features:
    - Configurable success/failure mode
    - Tracks all method calls for assertions
    - Simulates payment intent lifecycle
    - Supports idempotency key handling
    """

    provider_name = "mock"

    def __init__(self, should_fail: bool = False):
        """Initialize mock adapter.

        Args:
            should_fail: If True, all operations return failure
        """
        self._should_fail = should_fail
        self._calls: List[Dict[str, Any]] = []
        self._payment_intents: Dict[str, Dict[str, Any]] = {}
        self._idempotency_cache: Dict[str, str] = {}

    @property
    def calls(self) -> List[Dict[str, Any]]:
        """Return list of all method calls."""
        return self._calls

    def set_should_fail(self, should_fail: bool) -> None:
        """Toggle failure mode.

        Args:
            should_fail: If True, subsequent operations will fail
        """
        self._should_fail = should_fail

    def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        metadata: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> SDKResponse:
        """Create mock payment intent."""
        self._calls.append(
            {
                "method": "create_payment_intent",
                "amount": amount,
                "currency": currency,
                "metadata": metadata,
                "idempotency_key": idempotency_key,
            }
        )

        if self._should_fail:
            return SDKResponse(
                success=False, error="Mock payment failed", error_code="mock_error"
            )

        # Check idempotency cache
        if idempotency_key and idempotency_key in self._idempotency_cache:
            payment_intent_id = self._idempotency_cache[idempotency_key]
            return SDKResponse(
                success=True,
                data={
                    "payment_intent_id": payment_intent_id,
                    "amount": amount,
                    "currency": currency,
                    "status": "created",
                },
            )

        # Create new payment intent
        payment_intent_id = f"pi_mock_{uuid.uuid4().hex[:12]}"

        # Store in idempotency cache
        if idempotency_key:
            self._idempotency_cache[idempotency_key] = payment_intent_id

        # Store payment intent data
        self._payment_intents[payment_intent_id] = {
            "amount": amount,
            "currency": currency,
            "metadata": metadata,
            "status": "created",
        }

        return SDKResponse(
            success=True,
            data={
                "payment_intent_id": payment_intent_id,
                "amount": amount,
                "currency": currency,
                "status": "created",
            },
        )

    def capture_payment(
        self, payment_intent_id: str, idempotency_key: Optional[str] = None
    ) -> SDKResponse:
        """Capture mock payment."""
        self._calls.append(
            {
                "method": "capture_payment",
                "payment_intent_id": payment_intent_id,
                "idempotency_key": idempotency_key,
            }
        )

        if self._should_fail:
            return SDKResponse(
                success=False, error="Mock capture failed", error_code="mock_error"
            )

        if payment_intent_id not in self._payment_intents:
            return SDKResponse(
                success=False, error="Payment intent not found", error_code="not_found"
            )

        # Update status
        self._payment_intents[payment_intent_id]["status"] = "captured"

        return SDKResponse(
            success=True,
            data={"payment_intent_id": payment_intent_id, "status": "captured"},
        )

    def release_authorization(self, payment_intent_id: str) -> SDKResponse:
        return SDKResponse(
            success=True,
            data={"payment_intent_id": payment_intent_id, "status": "canceled"},
        )

    def refund_payment(
        self,
        payment_intent_id: str,
        amount: Optional[Decimal] = None,
        idempotency_key: Optional[str] = None,
    ) -> SDKResponse:
        """Refund mock payment."""
        self._calls.append(
            {
                "method": "refund_payment",
                "payment_intent_id": payment_intent_id,
                "amount": amount,
                "idempotency_key": idempotency_key,
            }
        )

        if self._should_fail:
            return SDKResponse(
                success=False, error="Mock refund failed", error_code="mock_error"
            )

        if payment_intent_id not in self._payment_intents:
            return SDKResponse(
                success=False, error="Payment intent not found", error_code="not_found"
            )

        intent = self._payment_intents[payment_intent_id]
        refund_amount = amount if amount is not None else intent["amount"]
        refund_id = f"re_mock_{uuid.uuid4().hex[:12]}"

        # Update status
        intent["status"] = "refunded"

        return SDKResponse(
            success=True,
            data={
                "refund_id": refund_id,
                "payment_intent_id": payment_intent_id,
                "amount": refund_amount,
                "status": "refunded",
            },
        )

    def get_payment_status(self, payment_intent_id: str) -> SDKResponse:
        """Get mock payment status."""
        self._calls.append(
            {"method": "get_payment_status", "payment_intent_id": payment_intent_id}
        )

        if self._should_fail:
            return SDKResponse(
                success=False, error="Mock status check failed", error_code="mock_error"
            )

        if payment_intent_id not in self._payment_intents:
            return SDKResponse(
                success=False, error="Payment intent not found", error_code="not_found"
            )

        intent = self._payment_intents[payment_intent_id]

        return SDKResponse(
            success=True,
            data={
                "payment_intent_id": payment_intent_id,
                "status": intent["status"],
                "amount": intent["amount"],
                "currency": intent["currency"],
            },
        )
