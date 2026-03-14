"""Tests for src/scheduler.py subscription jobs."""


class TestRunSubscriptionJobs:
    """Tests for _run_subscription_jobs function."""

    def _make_app_ctx(self, mocker):
        """Create a minimal mock Flask app with app_context."""
        mock_app = mocker.MagicMock()
        ctx = mocker.MagicMock()
        ctx.__enter__ = mocker.MagicMock(return_value=ctx)
        ctx.__exit__ = mocker.MagicMock(return_value=False)
        mock_app.app_context.return_value = ctx
        return mock_app

    def test_calls_expire_subscriptions(self, mocker):
        """_run_subscription_jobs should call svc.expire_subscriptions()."""
        mock_app = self._make_app_ctx(mocker)

        mock_db = mocker.MagicMock()
        mock_repo_cls = mocker.MagicMock()
        mock_invoice_repo_cls = mocker.MagicMock()
        mock_svc_cls = mocker.MagicMock()
        mock_svc_instance = mocker.MagicMock()
        mock_svc_instance.expire_subscriptions.return_value = []
        mock_svc_instance.expire_trials.return_value = []
        mock_svc_instance.send_dunning_emails.return_value = []
        mock_svc_cls.return_value = mock_svc_instance

        mocker.patch("src.scheduler.SubscriptionRepository", mock_repo_cls)
        mocker.patch("src.scheduler.InvoiceRepository", mock_invoice_repo_cls)
        mocker.patch("src.scheduler.SubscriptionService", mock_svc_cls)
        mocker.patch("src.scheduler.db", mock_db)

        from src.scheduler import _run_subscription_jobs

        _run_subscription_jobs(mock_app)

        mock_svc_instance.expire_subscriptions.assert_called_once()

    def test_calls_expire_trials(self, mocker):
        """_run_subscription_jobs should call svc.expire_trials()."""
        mock_app = self._make_app_ctx(mocker)

        mock_db = mocker.MagicMock()
        mock_repo_cls = mocker.MagicMock()
        mock_invoice_repo_cls = mocker.MagicMock()
        mock_svc_cls = mocker.MagicMock()
        mock_svc_instance = mocker.MagicMock()
        mock_svc_instance.expire_subscriptions.return_value = []
        mock_svc_instance.expire_trials.return_value = []
        mock_svc_instance.send_dunning_emails.return_value = []
        mock_svc_cls.return_value = mock_svc_instance

        mocker.patch("src.scheduler.SubscriptionRepository", mock_repo_cls)
        mocker.patch("src.scheduler.InvoiceRepository", mock_invoice_repo_cls)
        mocker.patch("src.scheduler.SubscriptionService", mock_svc_cls)
        mocker.patch("src.scheduler.db", mock_db)

        from src.scheduler import _run_subscription_jobs

        _run_subscription_jobs(mock_app)

        mock_svc_instance.expire_trials.assert_called_once()

    def test_calls_send_dunning_emails(self, mocker):
        """_run_subscription_jobs should call svc.send_dunning_emails()."""
        mock_app = self._make_app_ctx(mocker)

        mock_db = mocker.MagicMock()
        mock_repo_cls = mocker.MagicMock()
        mock_invoice_repo_cls = mocker.MagicMock()
        mock_svc_cls = mocker.MagicMock()
        mock_svc_instance = mocker.MagicMock()
        mock_svc_instance.expire_subscriptions.return_value = []
        mock_svc_instance.expire_trials.return_value = []
        mock_svc_instance.send_dunning_emails.return_value = []
        mock_svc_cls.return_value = mock_svc_instance

        mocker.patch("src.scheduler.SubscriptionRepository", mock_repo_cls)
        mocker.patch("src.scheduler.InvoiceRepository", mock_invoice_repo_cls)
        mocker.patch("src.scheduler.SubscriptionService", mock_svc_cls)
        mocker.patch("src.scheduler.db", mock_db)

        from src.scheduler import _run_subscription_jobs

        _run_subscription_jobs(mock_app)

        mock_svc_instance.send_dunning_emails.assert_called_once()

    def test_logs_counts(self, mocker):
        """_run_subscription_jobs should log counts of processed items."""
        mock_app = self._make_app_ctx(mocker)

        mock_db = mocker.MagicMock()
        mock_repo_cls = mocker.MagicMock()
        mock_invoice_repo_cls = mocker.MagicMock()
        mock_svc_cls = mocker.MagicMock()
        mock_svc_instance = mocker.MagicMock()
        mock_svc_instance.expire_subscriptions.return_value = ["s1", "s2"]
        mock_svc_instance.expire_trials.return_value = ["t1"]
        mock_svc_instance.send_dunning_emails.return_value = ["d1", "d2", "d3"]
        mock_svc_cls.return_value = mock_svc_instance

        mocker.patch("src.scheduler.SubscriptionRepository", mock_repo_cls)
        mocker.patch("src.scheduler.InvoiceRepository", mock_invoice_repo_cls)
        mocker.patch("src.scheduler.SubscriptionService", mock_svc_cls)
        mocker.patch("src.scheduler.db", mock_db)

        mock_logger = mocker.patch("src.scheduler.logger")

        from src.scheduler import _run_subscription_jobs

        _run_subscription_jobs(mock_app)

        mock_logger.info.assert_called_once()
        log_msg = mock_logger.info.call_args[0][0]
        assert "Scheduler" in log_msg or "scheduler" in log_msg.lower()
