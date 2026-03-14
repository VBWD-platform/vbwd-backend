"""APScheduler for subscription lifecycle jobs."""
import logging
from src.extensions import db
from src.repositories.subscription_repository import SubscriptionRepository
from src.repositories.invoice_repository import InvoiceRepository
from src.services.subscription_service import SubscriptionService

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
    scheduler.start()
    logger.info("[Scheduler] Subscription scheduler started (daily 00:05 UTC)")
    return scheduler
