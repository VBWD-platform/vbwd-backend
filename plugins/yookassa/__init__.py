"""YooKassa payment provider plugin."""
from typing import Optional, Dict, Any, TYPE_CHECKING
from decimal import Decimal
from uuid import UUID
from src.plugins.base import BasePlugin, PluginMetadata
from src.plugins.payment_provider import (
    PaymentProviderPlugin,
    PaymentResult,
    PaymentStatus,
)

if TYPE_CHECKING:
    from flask import Blueprint


class YooKassaPlugin(PaymentProviderPlugin):
    """YooKassa payment provider — REST API with redirect-based checkout.

    Class MUST be defined in __init__.py (not re-exported) due to
    discovery check obj.__module__ != full_module in manager.py.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="yookassa",
            version="1.0.0",
            author="VBWD Team",
            description="YooKassa payment provider — redirect checkout with webhooks",
            dependencies=[],
        )

    def get_blueprint(self) -> Optional["Blueprint"]:
        from plugins.yookassa.routes import yookassa_plugin_bp

        return yookassa_plugin_bp

    def get_url_prefix(self) -> Optional[str]:
        return "/api/v1/plugins/yookassa"

    def on_enable(self) -> None:
        pass  # Stateless — config read per-request from config_store

    def on_disable(self) -> None:
        pass

    def _get_adapter(self):
        """Instantiate YooKassaSDKAdapter from config_store (per-request)."""
        from flask import current_app
        from plugins.yookassa.sdk_adapter import YooKassaSDKAdapter
        from src.sdk.interface import SDKConfig

        config_store = current_app.config_store
        config = config_store.get_config("yookassa")
        prefix = "test_" if config.get("sandbox", True) else "live_"
        return YooKassaSDKAdapter(
            SDKConfig(
                api_key=config.get(f"{prefix}shop_id") or config.get("shop_id", ""),
                api_secret=config.get(f"{prefix}secret_key")
                or config.get("secret_key", ""),
                sandbox=config.get("sandbox", True),
            )
        )

    def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        subscription_id: UUID,
        user_id: UUID,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PaymentResult:
        adapter = self._get_adapter()
        meta = metadata or {}
        meta.update({"subscription_id": str(subscription_id), "user_id": str(user_id)})
        resp = adapter.create_payment_intent(amount, currency, meta)
        if resp.success:
            return PaymentResult(
                success=True,
                transaction_id=resp.data.get("session_id"),
                status=PaymentStatus.PENDING,
                metadata=resp.data,
            )
        return PaymentResult(success=False, error_message=resp.error)

    def process_payment(
        self, payment_intent_id: str, payment_method: str
    ) -> PaymentResult:
        adapter = self._get_adapter()
        resp = adapter.get_payment_status(payment_intent_id)
        if resp.success and resp.data.get("status") == "succeeded":
            return PaymentResult(
                success=True,
                transaction_id=payment_intent_id,
                status=PaymentStatus.COMPLETED,
            )
        return PaymentResult(
            success=False, error_message=resp.error or "Payment not yet completed"
        )

    def refund_payment(
        self, transaction_id: str, amount: Optional[Decimal] = None
    ) -> PaymentResult:
        adapter = self._get_adapter()
        resp = adapter.refund_payment(transaction_id, amount)
        if resp.success:
            return PaymentResult(
                success=True,
                transaction_id=resp.data.get("refund_id"),
                status=PaymentStatus.REFUNDED,
            )
        return PaymentResult(success=False, error_message=resp.error)

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        from flask import current_app

        config = current_app.config_store.get_config("yookassa")
        prefix = "test_" if config.get("sandbox", True) else "live_"
        webhook_secret = config.get(f"{prefix}webhook_secret") or config.get(
            "webhook_secret", ""
        )
        try:
            from plugins.yookassa.sdk_adapter import YooKassaSDKAdapter

            YooKassaSDKAdapter.verify_webhook_signature_static(
                payload, signature, webhook_secret
            )
            return True
        except ValueError:
            return False

    def handle_webhook(self, payload: Dict[str, Any]) -> None:
        pass  # Webhook handling is done in routes.py (event-driven)
