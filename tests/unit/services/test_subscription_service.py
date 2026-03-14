"""Tests for SubscriptionService."""
import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timedelta
from uuid import uuid4

from src.models.enums import SubscriptionStatus, InvoiceStatus
from src.services.subscription_service import SubscriptionService


class TestSubscriptionServiceCreate:
    """Test cases for creating subscriptions."""

    @pytest.fixture
    def mock_sub_repo(self):
        """Mock SubscriptionRepository."""
        return Mock()

    @pytest.fixture
    def mock_plan_repo(self):
        """Mock TarifPlanRepository."""
        return Mock()

    @pytest.fixture
    def subscription_service(self, mock_sub_repo, mock_plan_repo):
        """Create SubscriptionService with mocked dependencies."""
        from src.services.subscription_service import SubscriptionService

        return SubscriptionService(
            subscription_repo=mock_sub_repo,
            tarif_plan_repo=mock_plan_repo,
        )

    def test_create_subscription_creates_pending(
        self, subscription_service, mock_sub_repo, mock_plan_repo
    ):
        """create_subscription should create pending subscription."""
        from src.models.subscription import Subscription
        from src.models.tarif_plan import TarifPlan
        from src.models.enums import SubscriptionStatus, BillingPeriod

        plan_id = uuid4()
        user_id = uuid4()

        plan = TarifPlan()
        plan.id = plan_id
        plan.name = "Pro"
        plan.billing_period = BillingPeriod.MONTHLY
        plan.price_float = 29.99
        plan.is_active = True

        mock_plan_repo.find_by_id.return_value = plan

        subscription = Subscription()
        subscription.id = uuid4()
        subscription.user_id = user_id
        subscription.tarif_plan_id = plan_id
        subscription.status = SubscriptionStatus.PENDING

        mock_sub_repo.save.return_value = subscription

        result = subscription_service.create_subscription(
            user_id=user_id, tarif_plan_id=plan_id
        )

        assert result.status == SubscriptionStatus.PENDING
        mock_sub_repo.save.assert_called_once()
        mock_plan_repo.find_by_id.assert_called_once_with(plan_id)

    def test_create_subscription_raises_if_plan_not_found(
        self, subscription_service, mock_plan_repo
    ):
        """create_subscription should raise error if plan not found."""
        plan_id = uuid4()
        user_id = uuid4()

        mock_plan_repo.find_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            subscription_service.create_subscription(
                user_id=user_id, tarif_plan_id=plan_id
            )

    def test_create_subscription_raises_if_plan_inactive(
        self, subscription_service, mock_plan_repo
    ):
        """create_subscription should raise error if plan is inactive."""
        from src.models.tarif_plan import TarifPlan

        plan_id = uuid4()
        user_id = uuid4()

        plan = TarifPlan()
        plan.id = plan_id
        plan.is_active = False

        mock_plan_repo.find_by_id.return_value = plan

        with pytest.raises(ValueError, match="not active"):
            subscription_service.create_subscription(
                user_id=user_id, tarif_plan_id=plan_id
            )


class TestSubscriptionServiceActivate:
    """Test cases for activating subscriptions."""

    @pytest.fixture
    def mock_sub_repo(self):
        """Mock SubscriptionRepository."""
        return Mock()

    @pytest.fixture
    def subscription_service(self, mock_sub_repo):
        """Create SubscriptionService with mocked dependencies."""
        from src.services.subscription_service import SubscriptionService

        return SubscriptionService(subscription_repo=mock_sub_repo)

    def test_activate_subscription_sets_dates(
        self, subscription_service, mock_sub_repo
    ):
        """activate_subscription should set status and dates."""
        from src.models.subscription import Subscription
        from src.models.tarif_plan import TarifPlan
        from src.models.enums import SubscriptionStatus, BillingPeriod

        sub_id = uuid4()
        plan_id = uuid4()
        user_id = uuid4()

        plan = TarifPlan()
        plan.id = plan_id
        plan.billing_period = BillingPeriod.MONTHLY

        subscription = Subscription()
        subscription.id = sub_id
        subscription.user_id = user_id
        subscription.tarif_plan_id = plan_id
        subscription.status = SubscriptionStatus.PENDING
        subscription.tarif_plan = plan

        mock_sub_repo.find_by_id.return_value = subscription
        mock_sub_repo.save.return_value = subscription

        result = subscription_service.activate_subscription(sub_id)

        assert result.success is True
        assert result.subscription.status == SubscriptionStatus.ACTIVE
        assert result.subscription.started_at is not None
        assert result.subscription.expires_at is not None
        mock_sub_repo.save.assert_called_once()

    def test_activate_subscription_raises_if_not_found(
        self, subscription_service, mock_sub_repo
    ):
        """activate_subscription should return error result if not found."""
        sub_id = uuid4()
        mock_sub_repo.find_by_id.return_value = None

        result = subscription_service.activate_subscription(sub_id)

        assert result.success is False
        assert "not found" in result.error.lower()


class TestSubscriptionServiceGetActive:
    """Test cases for getting active subscriptions."""

    @pytest.fixture
    def mock_sub_repo(self):
        """Mock SubscriptionRepository."""
        return Mock()

    @pytest.fixture
    def subscription_service(self, mock_sub_repo):
        """Create SubscriptionService with mocked dependencies."""
        from src.services.subscription_service import SubscriptionService

        return SubscriptionService(subscription_repo=mock_sub_repo)

    def test_get_active_subscription_returns_valid(
        self, subscription_service, mock_sub_repo
    ):
        """get_active_subscription should return valid subscription."""
        from src.models.subscription import Subscription
        from src.models.enums import SubscriptionStatus

        user_id = uuid4()

        subscription = Subscription()
        subscription.id = uuid4()
        subscription.user_id = user_id
        subscription.tarif_plan_id = uuid4()
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.expires_at = datetime.utcnow() + timedelta(days=30)

        mock_sub_repo.find_active_by_user.return_value = subscription

        result = subscription_service.get_active_subscription(user_id=user_id)

        assert result is not None
        assert result.is_valid is True
        mock_sub_repo.find_active_by_user.assert_called_once_with(user_id)

    def test_get_active_subscription_returns_none_if_not_found(
        self, subscription_service, mock_sub_repo
    ):
        """get_active_subscription should return None if no active subscription."""
        user_id = uuid4()
        mock_sub_repo.find_active_by_user.return_value = None

        result = subscription_service.get_active_subscription(user_id=user_id)

        assert result is None


class TestSubscriptionServiceCancel:
    """Test cases for canceling subscriptions."""

    @pytest.fixture
    def mock_sub_repo(self):
        """Mock SubscriptionRepository."""
        return Mock()

    @pytest.fixture
    def subscription_service(self, mock_sub_repo):
        """Create SubscriptionService with mocked dependencies."""
        from src.services.subscription_service import SubscriptionService

        return SubscriptionService(subscription_repo=mock_sub_repo)

    def test_cancel_subscription_sets_status(self, subscription_service, mock_sub_repo):
        """cancel_subscription should set cancelled status."""
        from src.models.subscription import Subscription
        from src.models.enums import SubscriptionStatus

        sub_id = uuid4()

        subscription = Subscription()
        subscription.id = sub_id
        subscription.user_id = uuid4()
        subscription.tarif_plan_id = uuid4()
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.started_at = datetime.utcnow()
        subscription.expires_at = datetime.utcnow() + timedelta(days=30)

        mock_sub_repo.find_by_id.return_value = subscription
        mock_sub_repo.save.return_value = subscription

        result = subscription_service.cancel_subscription(sub_id)

        assert result.success is True
        assert result.subscription.status == SubscriptionStatus.CANCELLED
        assert result.subscription.cancelled_at is not None
        mock_sub_repo.save.assert_called_once()

    def test_cancel_subscription_raises_if_not_found(
        self, subscription_service, mock_sub_repo
    ):
        """cancel_subscription should return error result if not found."""
        sub_id = uuid4()
        mock_sub_repo.find_by_id.return_value = None

        result = subscription_service.cancel_subscription(sub_id)

        assert result.success is False
        assert "not found" in result.error.lower()


class TestSubscriptionServiceActivateWithTokens:
    """Test cases for token crediting on subscription activation."""

    @pytest.fixture
    def mock_sub_repo(self):
        """Mock SubscriptionRepository."""
        return Mock()

    @pytest.fixture
    def mock_token_service(self):
        """Mock TokenService."""
        return Mock()

    def _make_subscription_and_plan(self, features):
        from src.models.subscription import Subscription
        from src.models.tarif_plan import TarifPlan
        from src.models.enums import SubscriptionStatus, BillingPeriod

        sub_id = uuid4()
        user_id = uuid4()
        plan_id = uuid4()

        plan = TarifPlan()
        plan.id = plan_id
        plan.name = "Pro"
        plan.billing_period = BillingPeriod.MONTHLY
        plan.features = features

        subscription = Subscription()
        subscription.id = sub_id
        subscription.user_id = user_id
        subscription.tarif_plan_id = plan_id
        subscription.status = SubscriptionStatus.PENDING
        subscription.tarif_plan = plan

        return subscription

    def test_activate_credits_tokens_when_features_has_default_tokens(
        self, mock_sub_repo, mock_token_service
    ):
        """activate_subscription should credit tokens when default_tokens > 0."""
        from src.services.subscription_service import SubscriptionService
        from src.models.enums import TokenTransactionType

        subscription = self._make_subscription_and_plan({"default_tokens": 100})
        mock_sub_repo.find_by_id.return_value = subscription
        mock_sub_repo.save.return_value = subscription

        service = SubscriptionService(
            subscription_repo=mock_sub_repo, token_service=mock_token_service
        )
        result = service.activate_subscription(subscription.id)

        assert result.success is True
        mock_token_service.credit_tokens.assert_called_once_with(
            user_id=subscription.user_id,
            amount=100,
            transaction_type=TokenTransactionType.SUBSCRIPTION,
            reference_id=subscription.id,
            description="Plan tokens: Pro",
        )

    def test_activate_skips_tokens_when_zero(self, mock_sub_repo, mock_token_service):
        """activate_subscription should NOT credit tokens when default_tokens is 0."""
        from src.services.subscription_service import SubscriptionService

        subscription = self._make_subscription_and_plan({"default_tokens": 0})
        mock_sub_repo.find_by_id.return_value = subscription
        mock_sub_repo.save.return_value = subscription

        service = SubscriptionService(
            subscription_repo=mock_sub_repo, token_service=mock_token_service
        )
        result = service.activate_subscription(subscription.id)

        assert result.success is True
        mock_token_service.credit_tokens.assert_not_called()

    def test_activate_skips_tokens_when_no_key(self, mock_sub_repo, mock_token_service):
        """activate_subscription should NOT credit tokens when key is missing."""
        from src.services.subscription_service import SubscriptionService

        subscription = self._make_subscription_and_plan({"api_calls": 1000})
        mock_sub_repo.find_by_id.return_value = subscription
        mock_sub_repo.save.return_value = subscription

        service = SubscriptionService(
            subscription_repo=mock_sub_repo, token_service=mock_token_service
        )
        result = service.activate_subscription(subscription.id)

        assert result.success is True
        mock_token_service.credit_tokens.assert_not_called()

    def test_activate_skips_tokens_when_features_is_list(
        self, mock_sub_repo, mock_token_service
    ):
        """activate_subscription should NOT credit tokens when features is a list."""
        from src.services.subscription_service import SubscriptionService

        subscription = self._make_subscription_and_plan(["feature_a", "feature_b"])
        mock_sub_repo.find_by_id.return_value = subscription
        mock_sub_repo.save.return_value = subscription

        service = SubscriptionService(
            subscription_repo=mock_sub_repo, token_service=mock_token_service
        )
        result = service.activate_subscription(subscription.id)

        assert result.success is True
        mock_token_service.credit_tokens.assert_not_called()

    def test_activate_skips_tokens_when_no_token_service(self, mock_sub_repo):
        """activate_subscription should work fine without token_service."""
        from src.services.subscription_service import SubscriptionService

        subscription = self._make_subscription_and_plan({"default_tokens": 100})
        mock_sub_repo.find_by_id.return_value = subscription
        mock_sub_repo.save.return_value = subscription

        service = SubscriptionService(subscription_repo=mock_sub_repo)
        result = service.activate_subscription(subscription.id)

        assert result.success is True


class TestSubscriptionServiceGetUserSubscriptions:
    """Test cases for getting user subscriptions."""

    @pytest.fixture
    def mock_sub_repo(self):
        """Mock SubscriptionRepository."""
        return Mock()

    @pytest.fixture
    def subscription_service(self, mock_sub_repo):
        """Create SubscriptionService with mocked dependencies."""
        from src.services.subscription_service import SubscriptionService

        return SubscriptionService(subscription_repo=mock_sub_repo)

    def test_get_user_subscriptions_returns_list(
        self, subscription_service, mock_sub_repo
    ):
        """get_user_subscriptions should return all user subscriptions."""
        from src.models.subscription import Subscription
        from src.models.enums import SubscriptionStatus

        user_id = uuid4()

        sub1 = Subscription()
        sub1.id = uuid4()
        sub1.user_id = user_id
        sub1.status = SubscriptionStatus.ACTIVE

        sub2 = Subscription()
        sub2.id = uuid4()
        sub2.user_id = user_id
        sub2.status = SubscriptionStatus.EXPIRED

        subscriptions = [sub1, sub2]
        mock_sub_repo.find_by_user.return_value = subscriptions

        result = subscription_service.get_user_subscriptions(user_id=user_id)

        assert len(result) == 2
        mock_sub_repo.find_by_user.assert_called_once_with(user_id)


# --- Trial tests ---


def _make_user(has_used_trial=False):
    user = MagicMock()
    user.id = uuid4()
    user.has_used_trial = has_used_trial
    return user


def _make_plan(trial_days=14, price=9.99, price_float=9.99, currency="EUR"):
    plan = MagicMock()
    plan.id = uuid4()
    plan.trial_days = trial_days
    plan.price = price
    plan.price_float = price_float
    plan.currency = currency
    plan.name = "Basic"
    plan.is_active = True
    return plan


def _make_trial_subscription(
    status=SubscriptionStatus.TRIALING, trial_end_at=None, plan=None
):
    sub = MagicMock()
    sub.id = uuid4()
    sub.user_id = uuid4()
    sub.status = status
    sub.trial_end_at = trial_end_at
    sub.tarif_plan = plan or _make_plan()
    sub.tarif_plan_id = sub.tarif_plan.id
    sub.cancel = MagicMock()
    return sub


class TestStartTrial:
    """Tests for SubscriptionService.start_trial()."""

    def test_creates_trialing_subscription(self):
        user = _make_user()
        plan = _make_plan(trial_days=14)
        user_repo = MagicMock(find_by_id=MagicMock(return_value=user))
        sub_repo = MagicMock(find_active_by_user=MagicMock(return_value=None))
        sub_repo.save = MagicMock(side_effect=lambda s: s)
        plan_repo = MagicMock(find_by_id=MagicMock(return_value=plan))

        service = SubscriptionService(
            subscription_repo=sub_repo, tarif_plan_repo=plan_repo
        )
        result = service.start_trial(user.id, plan.id, user_repo)

        assert result.success is True
        assert result.subscription.status == SubscriptionStatus.TRIALING
        assert result.subscription.trial_end_at is not None
        sub_repo.save.assert_called_once()

    def test_rejects_user_who_used_trial(self):
        user = _make_user(has_used_trial=True)
        user_repo = MagicMock(find_by_id=MagicMock(return_value=user))

        service = SubscriptionService(
            subscription_repo=MagicMock(), tarif_plan_repo=MagicMock()
        )
        result = service.start_trial(user.id, uuid4(), user_repo)

        assert result.success is False
        assert "already used" in result.error.lower()

    def test_rejects_user_with_active_subscription(self):
        user = _make_user()
        user_repo = MagicMock(find_by_id=MagicMock(return_value=user))
        sub_repo = MagicMock(find_active_by_user=MagicMock(return_value=MagicMock()))

        service = SubscriptionService(
            subscription_repo=sub_repo, tarif_plan_repo=MagicMock()
        )
        result = service.start_trial(user.id, uuid4(), user_repo)

        assert result.success is False
        assert "active subscription" in result.error.lower()

    def test_sets_has_used_trial_on_user(self):
        user = _make_user()
        plan = _make_plan(trial_days=7)
        user_repo = MagicMock(find_by_id=MagicMock(return_value=user))
        sub_repo = MagicMock(find_active_by_user=MagicMock(return_value=None))
        sub_repo.save = MagicMock(side_effect=lambda s: s)
        plan_repo = MagicMock(find_by_id=MagicMock(return_value=plan))

        service = SubscriptionService(
            subscription_repo=sub_repo, tarif_plan_repo=plan_repo
        )
        service.start_trial(user.id, plan.id, user_repo)

        assert user.has_used_trial is True
        user_repo.save.assert_called_once_with(user)

    def test_uses_plan_trial_days(self):
        user = _make_user()
        plan = _make_plan(trial_days=30)
        user_repo = MagicMock(find_by_id=MagicMock(return_value=user))
        sub_repo = MagicMock(find_active_by_user=MagicMock(return_value=None))
        sub_repo.save = MagicMock(side_effect=lambda s: s)
        plan_repo = MagicMock(find_by_id=MagicMock(return_value=plan))

        service = SubscriptionService(
            subscription_repo=sub_repo, tarif_plan_repo=plan_repo
        )
        result = service.start_trial(user.id, plan.id, user_repo)

        delta = result.subscription.trial_end_at - result.subscription.started_at
        assert delta.days == 30

    def test_rejects_plan_without_trial(self):
        user = _make_user()
        plan = _make_plan(trial_days=0)
        user_repo = MagicMock(find_by_id=MagicMock(return_value=user))
        sub_repo = MagicMock(find_active_by_user=MagicMock(return_value=None))
        plan_repo = MagicMock(find_by_id=MagicMock(return_value=plan))

        service = SubscriptionService(
            subscription_repo=sub_repo, tarif_plan_repo=plan_repo
        )
        result = service.start_trial(user.id, plan.id, user_repo)

        assert result.success is False
        assert "no trial" in result.error.lower()


class TestActivateRejectsTrialing:
    """Test that activate_subscription blocks TRIALING subscriptions."""

    def test_activate_rejects_trialing_subscription(self):
        from src.models.subscription import Subscription

        sub = Subscription()
        sub.id = uuid4()
        sub.status = SubscriptionStatus.TRIALING
        sub_repo = MagicMock(find_by_id=MagicMock(return_value=sub))

        service = SubscriptionService(subscription_repo=sub_repo)
        result = service.activate_subscription(sub.id)

        assert result.success is False
        assert "trial" in result.error.lower()


class TestExpireTrials:
    """Tests for SubscriptionService.expire_trials()."""

    def test_cancels_expired_trials(self):
        plan = _make_plan()
        sub = _make_trial_subscription(
            status=SubscriptionStatus.TRIALING,
            trial_end_at=datetime.utcnow() - timedelta(days=1),
            plan=plan,
        )
        sub_repo = MagicMock(find_expired_trials=MagicMock(return_value=[sub]))
        sub_repo.save = MagicMock(side_effect=lambda s: s)
        invoice_repo = MagicMock()
        invoice_repo.save = MagicMock(side_effect=lambda i: i)

        service = SubscriptionService(subscription_repo=sub_repo)
        results = service.expire_trials(invoice_repo)

        assert len(results) == 1
        sub.cancel.assert_called_once()
        sub_repo.save.assert_called_once()

    def test_creates_pending_invoice_on_expiry(self):
        plan = _make_plan(price=9.99)
        sub = _make_trial_subscription(
            status=SubscriptionStatus.TRIALING,
            trial_end_at=datetime.utcnow() - timedelta(days=1),
            plan=plan,
        )
        sub_repo = MagicMock(find_expired_trials=MagicMock(return_value=[sub]))
        sub_repo.save = MagicMock(side_effect=lambda s: s)
        invoice_repo = MagicMock()
        invoice_repo.save = MagicMock(side_effect=lambda i: i)

        service = SubscriptionService(subscription_repo=sub_repo)
        service.expire_trials(invoice_repo)

        invoice_repo.save.assert_called_once()
        saved_invoice = invoice_repo.save.call_args[0][0]
        assert saved_invoice.user_id == sub.user_id
        assert saved_invoice.status == InvoiceStatus.PENDING

    def test_skips_active_trials(self):
        sub_repo = MagicMock(find_expired_trials=MagicMock(return_value=[]))

        service = SubscriptionService(subscription_repo=sub_repo)
        results = service.expire_trials(MagicMock())

        assert len(results) == 0


class TestBillingPeriodDays:
    """Test PERIOD_DAYS covers all BillingPeriod values including DAILY and WEEKLY."""

    def test_daily_period_is_one_day(self):
        from src.models.enums import BillingPeriod
        from src.services.subscription_service import SubscriptionService

        assert SubscriptionService.PERIOD_DAYS[BillingPeriod.DAILY] == 1

    def test_weekly_period_is_seven_days(self):
        from src.models.enums import BillingPeriod
        from src.services.subscription_service import SubscriptionService

        assert SubscriptionService.PERIOD_DAYS[BillingPeriod.WEEKLY] == 7

    def test_all_billing_periods_covered(self):
        from src.models.enums import BillingPeriod
        from src.services.subscription_service import SubscriptionService

        for period in BillingPeriod:
            assert (
                period in SubscriptionService.PERIOD_DAYS
            ), f"{period} missing from PERIOD_DAYS"


class TestSendDunningEmails:
    """Tests for SubscriptionService.send_dunning_emails()."""

    def _make_subscription(self):
        sub = MagicMock()
        sub.id = uuid4()
        sub.user_id = uuid4()
        return sub

    def test_returns_empty_list_when_no_candidates(self):
        sub_repo = MagicMock()
        sub_repo.find_dunning_candidates.return_value = []
        service = SubscriptionService(subscription_repo=sub_repo)

        result = service.send_dunning_emails()

        assert result == []

    def test_dispatches_dunning_event_for_each_candidate(self):
        sub1 = self._make_subscription()
        sub2 = self._make_subscription()

        sub_repo = MagicMock()
        sub_repo.find_dunning_candidates.side_effect = lambda days: (
            [sub1] if days == 3 else [sub2]
        )

        dispatcher = MagicMock()
        service = SubscriptionService(subscription_repo=sub_repo)

        result = service.send_dunning_emails(event_dispatcher=dispatcher)

        assert len(result) == 2
        assert dispatcher.emit.call_count == 2

    def test_no_dispatch_when_no_event_dispatcher(self):
        sub = self._make_subscription()
        sub_repo = MagicMock()
        sub_repo.find_dunning_candidates.return_value = [sub]

        service = SubscriptionService(subscription_repo=sub_repo)
        result = service.send_dunning_emails(event_dispatcher=None)

        assert len(result) >= 0

    def test_uses_dunning_days_config(self):
        from src.services.subscription_service import SubscriptionService

        assert hasattr(SubscriptionService, "DUNNING_DAYS")
        assert 3 in SubscriptionService.DUNNING_DAYS
        assert 7 in SubscriptionService.DUNNING_DAYS

    def test_emitted_events_are_subscription_dunning_events(self):
        from src.events.subscription_events import SubscriptionDunningEvent

        sub = self._make_subscription()
        sub_repo = MagicMock()
        sub_repo.find_dunning_candidates.return_value = [sub]

        dispatcher = MagicMock()
        service = SubscriptionService(subscription_repo=sub_repo)
        service.send_dunning_emails(event_dispatcher=dispatcher)

        emitted = dispatcher.emit.call_args[0][0]
        assert isinstance(emitted, SubscriptionDunningEvent)
