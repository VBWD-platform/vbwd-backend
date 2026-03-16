"""YooKassa SDK adapter implementing ISDKAdapter."""
import hashlib
import hmac
import uuid as uuid_mod
from decimal import Decimal
from typing import Dict, Any, Optional

import requests

from src.sdk.base import BaseSDKAdapter
from src.sdk.interface import SDKConfig, SDKResponse


class YooKassaSDKAdapter(BaseSDKAdapter):
    """YooKassa SDK adapter implementing ISDKAdapter.

    Uses YooKassa Payments API v3 (redirect-based checkout).
    Auth: HTTP Basic Auth (shop_id : secret_key).
    Base URL is the same for test and live — mode depends on credentials.
    Liskov Substitution: interchangeable with any ISDKAdapter.
    """

    BASE_URL = "https://api.yookassa.ru/v3"

    def __init__(self, config: SDKConfig, idempotency_service=None):
        super().__init__(config, idempotency_service)
        self._shop_id = config.api_key
        self._secret_key = config.api_secret or ""

    @property
    def provider_name(self) -> str:
        return "yookassa"

    def _auth(self):
        """HTTP Basic Auth tuple."""
        return (self._shop_id, self._secret_key)

    def _headers(self, idempotency_key: Optional[str] = None) -> Dict[str, str]:
        """Build request headers with optional idempotency key."""
        headers = {"Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotence-Key"] = idempotency_key
        return headers

    def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        metadata: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> SDKResponse:
        """Create YooKassa payment for one-time or recurring payment.

        For recurring (save_payment_method=True), the payment method is
        saved for future charges.
        """
        idem_key = idempotency_key or str(uuid_mod.uuid4())

        def _create():
            payment_data: Dict[str, Any] = {
                "amount": {
                    "value": str(amount),
                    "currency": currency.upper(),
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": metadata.get("success_url", ""),
                },
                "capture": True,
                "metadata": {
                    "invoice_id": metadata.get("invoice_id", ""),
                    "user_id": metadata.get("user_id", ""),
                },
            }
            if metadata.get("save_payment_method"):
                payment_data["save_payment_method"] = True
            if metadata.get("payment_method_id"):
                payment_data["payment_method_id"] = metadata["payment_method_id"]
                payment_data["confirm"] = True
                # No confirmation needed for recurring
                payment_data.pop("confirmation", None)

            resp = requests.post(
                f"{self.BASE_URL}/payments",
                json=payment_data,
                auth=self._auth(),
                headers=self._headers(idem_key),
                timeout=self._config.timeout,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                confirmation = data.get("confirmation", {})
                return SDKResponse(
                    success=True,
                    data={
                        "session_id": data["id"],
                        "session_url": confirmation.get("confirmation_url", ""),
                        "status": data.get("status", ""),
                        "payment_method_id": data.get("payment_method", {}).get(
                            "id", ""
                        ),
                    },
                )
            return SDKResponse(
                success=False, error=resp.text, error_code=str(resp.status_code)
            )

        return self._with_idempotency(idempotency_key, _create)

    def capture_payment(
        self, payment_intent_id: str, idempotency_key: Optional[str] = None
    ) -> SDKResponse:
        """Capture a two-step payment (not used with capture=True)."""
        idem_key = idempotency_key or str(uuid_mod.uuid4())

        def _capture():
            resp = requests.post(
                f"{self.BASE_URL}/payments/{payment_intent_id}/capture",
                json={},
                auth=self._auth(),
                headers=self._headers(idem_key),
                timeout=self._config.timeout,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                return SDKResponse(
                    success=True,
                    data={
                        "payment_id": data["id"],
                        "status": data.get("status", ""),
                        "amount": data.get("amount", {}).get("value", "0"),
                        "currency": data.get("amount", {}).get("currency", "RUB"),
                    },
                )
            return SDKResponse(
                success=False, error=resp.text, error_code=str(resp.status_code)
            )

        return self._with_idempotency(idempotency_key, _capture)

    def get_payment_status(self, payment_id: str) -> SDKResponse:
        """Get YooKassa payment status."""
        resp = requests.get(
            f"{self.BASE_URL}/payments/{payment_id}",
            auth=self._auth(),
            headers=self._headers(),
            timeout=self._config.timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            return SDKResponse(
                success=True,
                data={
                    "status": data.get("status", ""),
                    "amount_total": data.get("amount", {}).get("value", "0"),
                    "currency": data.get("amount", {}).get("currency", "RUB"),
                    "invoice_id": data.get("metadata", {}).get("invoice_id", ""),
                    "payment_method_id": data.get("payment_method", {}).get("id", ""),
                    "payment_method_saved": data.get("payment_method", {}).get(
                        "saved", False
                    ),
                },
            )
        return SDKResponse(
            success=False, error=resp.text, error_code=str(resp.status_code)
        )

    def refund_payment(
        self,
        payment_id: str,
        amount: Optional[Decimal] = None,
        idempotency_key: Optional[str] = None,
    ) -> SDKResponse:
        """Refund a YooKassa payment."""
        idem_key = idempotency_key or str(uuid_mod.uuid4())

        def _refund():
            refund_data: Dict[str, Any] = {"payment_id": payment_id}
            if amount is not None:
                refund_data["amount"] = {
                    "value": str(amount),
                    "currency": "RUB",
                }
            resp = requests.post(
                f"{self.BASE_URL}/refunds",
                json=refund_data,
                auth=self._auth(),
                headers=self._headers(idem_key),
                timeout=self._config.timeout,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                return SDKResponse(
                    success=True,
                    data={"refund_id": data["id"], "status": data["status"]},
                )
            return SDKResponse(
                success=False, error=resp.text, error_code=str(resp.status_code)
            )

        return self._with_idempotency(idempotency_key, _refund)

    @staticmethod
    def verify_webhook_signature_static(
        payload: bytes, signature: str, webhook_secret: str
    ) -> dict:
        """Verify YooKassa webhook signature using HMAC-SHA256.

        YooKassa signs the request body with the webhook secret.
        """
        import json

        expected = hmac.new(
            webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid YooKassa webhook signature")
        return json.loads(payload)

    def verify_webhook_signature(
        self, payload: bytes, signature: str, webhook_secret: str
    ) -> dict:
        """Instance method wrapper for static verification."""
        return self.verify_webhook_signature_static(payload, signature, webhook_secret)
