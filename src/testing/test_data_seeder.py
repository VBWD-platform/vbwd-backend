"""
Test Data Seeder - Creates and cleans up test data in PostgreSQL.

Environment Variables:
    TEST_DATA_SEED: When 'true', seeds test data before tests
    TEST_DATA_CLEANUP: When 'true', removes test data after tests
    TEST_USER_EMAIL: Email for test user (default: test@example.com)
    TEST_USER_PASSWORD: Password for test user (default: TestPass123@)
    TEST_ADMIN_EMAIL: Email for test admin (default: admin@example.com)
    TEST_ADMIN_PASSWORD: Password for test admin (default: AdminPass123@)

Usage:
    # Programmatic
    seeder = TestDataSeeder(db.session)
    seeder.seed()    # Creates test data if TEST_DATA_SEED=true
    seeder.cleanup() # Removes test data if TEST_DATA_CLEANUP=true

    # CLI
    flask seed-test-data
    flask cleanup-test-data
"""
import os
from typing import Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
import bcrypt

from src.models.user import User
from src.models.enums import UserStatus, UserRole, SubscriptionStatus, BillingPeriod
from src.models.tarif_plan import TarifPlan
from src.models.subscription import Subscription


class TestDataSeeder:
    """
    Manages test data lifecycle in the database.

    SRP: Single responsibility - only handles test data seeding/cleanup.
    DIP: Depends on Session abstraction, not concrete database.
    """

    # Marker to identify test data for cleanup
    TEST_DATA_MARKER = "TEST_DATA_"

    def __init__(self, db_session: Session):
        """
        Initialize seeder with database session.

        Args:
            db_session: SQLAlchemy session for database operations.
        """
        self.session = db_session

    def should_seed(self) -> bool:
        """
        Check if seeding is enabled via environment.

        Returns:
            True if TEST_DATA_SEED environment variable is 'true' (case-insensitive).
        """
        return os.getenv("TEST_DATA_SEED", "false").lower() == "true"

    def should_cleanup(self) -> bool:
        """
        Check if cleanup is enabled via environment.

        Returns:
            True if TEST_DATA_CLEANUP environment variable is 'true' (case-insensitive).
        """
        return os.getenv("TEST_DATA_CLEANUP", "false").lower() == "true"

    def seed(self) -> bool:
        """
        Seed test data into the database.

        Creates test user, admin, tariff plan, and subscription if
        TEST_DATA_SEED environment variable is 'true'.

        Returns:
            bool: True if seeding was performed, False if skipped.
        """
        if not self.should_seed():
            return False

        # Create test user
        test_user = self._create_test_user()

        # Create test admin
        self._create_test_admin()

        # Create test tariff plan
        test_plan = self._create_test_plan()

        # Create test subscription for user
        if test_user and test_plan:
            self._create_test_subscription(test_user, test_plan)

        self.session.commit()
        return True

    def cleanup(self) -> bool:
        """
        Remove test data from the database.

        Deletes test users, subscriptions, and plans if
        TEST_DATA_CLEANUP environment variable is 'true'.

        Returns:
            bool: True if cleanup was performed, False if skipped.
        """
        if not self.should_cleanup():
            return False

        # Delete in reverse order of dependencies
        self._cleanup_subscriptions()
        self._cleanup_users()
        self._cleanup_plans()

        self.session.commit()
        return True

    def _hash_password(self, password: str) -> str:
        """
        Hash a password using bcrypt.

        Args:
            password: Plain text password.

        Returns:
            Hashed password string.
        """
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def _create_test_user(self) -> Optional[User]:
        """
        Create test user if not exists, or reset password if it does.

        Returns:
            Created or existing User, or None on error.
        """
        email = os.getenv("TEST_USER_EMAIL", "test@example.com")
        password = os.getenv("TEST_USER_PASSWORD", "TestPass123@")

        existing = self.session.query(User).filter_by(email=email).first()
        if existing:
            # Reset password to known state for test consistency
            existing.password_hash = self._hash_password(password)
            self.session.flush()
            return existing

        user = User(
            email=email,
            password_hash=self._hash_password(password),
            status=UserStatus.ACTIVE,
            role=UserRole.USER,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def _create_test_admin(self) -> Optional[User]:
        """
        Create test admin user if not exists.

        Returns:
            Created or existing admin User, or None on error.
        """
        email = os.getenv("TEST_ADMIN_EMAIL", "admin@example.com")
        password = os.getenv("TEST_ADMIN_PASSWORD", "AdminPass123@")

        existing = self.session.query(User).filter_by(email=email).first()
        if existing:
            return existing

        admin = User(
            email=email,
            password_hash=self._hash_password(password),
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        self.session.add(admin)
        self.session.flush()
        return admin

    def _create_test_plan(self) -> Optional[TarifPlan]:
        """
        Create test tariff plan if not exists.

        Returns:
            Created or existing TarifPlan, or None on error.
        """
        plan_name = f"{self.TEST_DATA_MARKER}Basic Plan"
        plan_slug = "test-data-basic-plan"

        existing = self.session.query(TarifPlan).filter_by(slug=plan_slug).first()
        if existing:
            return existing

        plan = TarifPlan(
            name=plan_name,
            slug=plan_slug,
            description="Test plan for integration tests",
            price_float=9.99,
            price=9.99,
            currency="EUR",
            is_active=True,
            billing_period=BillingPeriod.MONTHLY,
            features={"api_calls": 1000, "storage_gb": 5},
            sort_order=999,  # Put at the end
        )
        self.session.add(plan)
        self.session.flush()
        return plan

    def _create_test_subscription(
        self, user: User, plan: TarifPlan
    ) -> Optional[Subscription]:
        """
        Create test subscription for user.

        Args:
            user: User to create subscription for.
            plan: TarifPlan to subscribe to.

        Returns:
            Created or existing Subscription, or None on error.
        """
        existing = self.session.query(Subscription).filter_by(user_id=user.id).first()
        if existing:
            return existing

        subscription = Subscription(
            user_id=user.id,
            tarif_plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE,
            started_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        self.session.add(subscription)
        self.session.flush()
        return subscription

    def _cleanup_subscriptions(self) -> None:
        """Remove test subscriptions."""
        test_emails = [
            os.getenv("TEST_USER_EMAIL", "test@example.com"),
            os.getenv("TEST_ADMIN_EMAIL", "admin@example.com"),
        ]
        users = self.session.query(User).filter(User.email.in_(test_emails)).all()
        for user in users:
            self.session.query(Subscription).filter_by(user_id=user.id).delete(
                synchronize_session=False
            )

    def _cleanup_users(self) -> None:
        """Remove test users."""
        test_emails = [
            os.getenv("TEST_USER_EMAIL", "test@example.com"),
            os.getenv("TEST_ADMIN_EMAIL", "admin@example.com"),
        ]
        self.session.query(User).filter(User.email.in_(test_emails)).delete(
            synchronize_session=False
        )

    def _cleanup_plans(self) -> None:
        """Remove test plans (identified by marker prefix or slug)."""
        self.session.query(TarifPlan).filter(
            TarifPlan.slug == "test-data-basic-plan"
        ).delete(synchronize_session=False)
