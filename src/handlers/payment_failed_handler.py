"""Handler for PaymentFailedEvent — sets payment_failed_at on subscription."""
from src.utils.datetime_utils import utcnow
from src.events.domain import DomainEvent, EventResult, IEventHandler
from src.events.payment_events import PaymentFailedEvent


class PaymentFailedHandler(IEventHandler):
    """Sets payment_failed_at on the subscription when payment fails."""

    def __init__(self, container):
        self._container = container

    def can_handle(self, event: DomainEvent) -> bool:
        return isinstance(event, PaymentFailedEvent)

    def handle(self, event: DomainEvent) -> EventResult:
        if not isinstance(event, PaymentFailedEvent):
            return EventResult.error_result("Invalid event type")

        try:
            repo = self._container.subscription_repository()
            subscription = repo.find_by_id(event.subscription_id)
            if subscription and subscription.payment_failed_at is None:
                subscription.payment_failed_at = utcnow()
                repo.save(subscription)
            return EventResult.success_result(
                {"subscription_id": str(event.subscription_id)}
            )
        except Exception as e:
            return EventResult.error_result(str(e))
