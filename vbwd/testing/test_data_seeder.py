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

Core seeds the test user + admin. Subscription test data (plan +
subscription for the test user) is owned by the subscription plugin and
contributed via the demo-data registry — no-op when the plugin is
disabled. Core no longer imports subscription models.
"""
import os
from typing import Optional
from sqlalchemy.orm import Session
import bcrypt

from vbwd.models.user import User
from vbwd.models.enums import UserStatus, UserRole
from vbwd.services.demo_data_registry import (
    run_test_data_seeders,
    run_test_data_cleaners,
)


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

        Creates test user + admin (core). Subscription plan/subscription
        for the test user is contributed by the subscription plugin via
        the demo-data registry. Runs only if TEST_DATA_SEED is 'true'.

        Returns:
            bool: True if seeding was performed, False if skipped.
        """
        if not self.should_seed():
            return False

        # Create test user
        test_user = self._create_test_user()

        # Create test admin
        self._create_test_admin()

        # Plugin-contributed test data (e.g. subscription plan +
        # subscription for the test user). No-op if no plugin registered.
        if test_user:
            run_test_data_seeders(self.session, test_user)

        self.session.commit()
        return True

    def cleanup(self) -> bool:
        """
        Remove test data from the database.

        Plugin-contributed test data is cleaned first (FK order), then the
        core test users. Runs only if TEST_DATA_CLEANUP is 'true'.

        Returns:
            bool: True if cleanup was performed, False if skipped.
        """
        if not self.should_cleanup():
            return False

        # Plugin-owned test data first (children before the user rows).
        run_test_data_cleaners(self.session)
        self._cleanup_users()

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

    def _cleanup_users(self) -> None:
        """Remove test users."""
        test_emails = [
            os.getenv("TEST_USER_EMAIL", "test@example.com"),
            os.getenv("TEST_ADMIN_EMAIL", "admin@example.com"),
        ]
        self.session.query(User).filter(User.email.in_(test_emails)).delete(
            synchronize_session=False
        )
