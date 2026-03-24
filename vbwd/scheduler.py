"""APScheduler for subscription lifecycle jobs."""
import logging
from vbwd.extensions import db
from vbwd.repositories.subscription_repository import SubscriptionRepository
from vbwd.repositories.invoice_repository import InvoiceRepository
from vbwd.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


def _run_subscription_jobs(app):
    with app.app_context():
        repo = SubscriptionRepository(db.session)
        invoice_repo = InvoiceRepository(db.session)
        svc = SubscriptionService(repo)
        expired = svc.expire_subscriptions()
        trials = svc.expire_trials(invoice_repo)
        dunning = svc.send_dunning_emails()
        logger.info(
            "[Scheduler] Expired %d subscriptions, %d trials, %d dunning",
            len(expired),
            len(trials),
            len(dunning),
        )


def _run_booking_completion_jobs(app):
    """Auto-complete bookings whose time has passed."""
    with app.app_context():
        try:
            from plugins.booking.booking.repositories.booking_repository import (
                BookingRepository,
            )
            from plugins.booking.booking.repositories.resource_repository import (
                ResourceRepository,
            )
            from plugins.booking.booking.services.booking_completion_service import (
                BookingCompletionService,
            )
            from vbwd.events.bus import event_bus

            service = BookingCompletionService(
                booking_repository=BookingRepository(db.session),
                resource_repository=ResourceRepository(db.session),
                event_bus=event_bus,
            )
            completed = service.complete_past_bookings()
            if completed:
                db.session.commit()
                logger.info("[Scheduler] Auto-completed %d booking(s)", len(completed))
        except ImportError:
            pass  # Booking plugin not installed


def start_subscription_scheduler(app):
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _run_subscription_jobs,
        args=[app],
        trigger="cron",
        hour=0,
        minute=5,
        id="subscription_jobs",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_booking_completion_jobs,
        args=[app],
        trigger="interval",
        minutes=15,
        id="booking_completion_jobs",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[Scheduler] Subscription scheduler started (daily 00:05 UTC)")
    logger.info("[Scheduler] Booking completion scheduler started (every 15 min)")
    return scheduler
