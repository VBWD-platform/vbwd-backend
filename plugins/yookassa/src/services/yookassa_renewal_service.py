"""YooKassa renewal service for charging saved payment methods."""


class YooKassaRenewalService:
    """Service for auto-renewing subscriptions via saved YooKassa payment methods."""

    def __init__(self, shop_id: str, secret_key: str):
        self._shop_id = shop_id
        self._secret_key = secret_key

    def charge_saved_method(self, subscription, invoice) -> dict:
        payment_method_id = subscription.provider_subscription_id
        if not payment_method_id:
            raise ValueError("No saved payment method for subscription")

        import yookassa

        yookassa.Configuration.account_id = self._shop_id
        yookassa.Configuration.secret_key = self._secret_key

        idempotency_key = str(invoice.id)
        response = yookassa.Payment.create(
            {
                "amount": {
                    "value": str(invoice.amount),
                    "currency": invoice.currency or "RUB",
                },
                "capture": True,
                "payment_method_id": payment_method_id,
                "description": f"Renewal: {invoice.id}",
                "metadata": {
                    "invoice_id": str(invoice.id),
                    "subscription_id": str(subscription.id),
                    "renewal": "true",
                },
            },
            idempotency_key,
        )
        return response
