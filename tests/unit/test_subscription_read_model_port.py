"""Guards for the generic subscription read-model port (core stays agnostic)."""
from vbwd.services.subscription_read_model import (
    ISubscriptionReadModel,
    resolve_subscription_read_model,
    register_subscription_read_model,
    clear_subscription_read_model,
)


def test_null_default_active_subscription_count_is_zero():
    """No plugin registered → analytics reads 0, not an error."""
    clear_subscription_read_model()
    rm = resolve_subscription_read_model()
    assert rm.active_subscription_count() == 0


def test_registered_read_model_supplies_active_count():
    class _Fake(ISubscriptionReadModel):
        def enrich_invoice(self, invoice):
            return {}

        def count_user_subscriptions(self, user_id):
            return 0

        def user_addon_subscriptions(self, user_id):
            return []

        def active_subscription_count(self):
            return 5

    try:
        register_subscription_read_model(_Fake())
        assert resolve_subscription_read_model().active_subscription_count() == 5
    finally:
        clear_subscription_read_model()
