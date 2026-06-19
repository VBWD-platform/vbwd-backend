"""CLI for the outbound webhook delivery drain (core).

``flask webhooks deliver-due`` runs one drain pass — useful for manual
operation, cron-driven delivery, or debugging when the in-process scheduler is
not desired. It performs exactly the same work as one scheduler tick.
"""
import click
from flask import current_app
from flask.cli import AppGroup

from vbwd.extensions import db
from vbwd.repositories.webhook_delivery_repository import WebhookDeliveryRepository
from vbwd.repositories.webhook_subscription_repository import (
    WebhookSubscriptionRepository,
)
from vbwd.webhooks.outbound_service import OutboundWebhookService

webhooks_cli = AppGroup("webhooks", help="Outbound webhook delivery commands.")


@webhooks_cli.command("deliver-due")
@click.option("--limit", default=100, show_default=True, help="Max deliveries.")
def deliver_due_command(limit: int) -> None:
    """Drain due webhook deliveries (one pass)."""
    service = OutboundWebhookService(
        subscription_repository=WebhookSubscriptionRepository(db.session),
        delivery_repository=WebhookDeliveryRepository(db.session),
    )
    attempted = service.deliver_due(limit=limit)
    click.echo(f"Attempted {attempted} due webhook deliveries.")
    current_app.logger.info("[webhook] CLI drain attempted %d deliveries", attempted)
