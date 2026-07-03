"""User repository implementation."""
from typing import Optional, List, Tuple, Union
from uuid import UUID
from sqlalchemy import delete as sa_delete
from vbwd.repositories.base import BaseRepository
from vbwd.models import User
from vbwd.models.enums import UserRole, UserStatus


class UserRepository(BaseRepository[User]):
    """Repository for User entity operations."""

    def __init__(self, session):
        super().__init__(session=session, model=User)

    def delete(self, id: Union[UUID, str]) -> bool:
        """Delete a user by id, relying on database FK cascade.

        Overrides the base ORM ``session.delete(entity)`` path on purpose.
        The user graph fans out into plugin-owned tables (subscriptions,
        addons, invoices, ...) whose FK cascade is only known to the
        database, not to the ORM relationship map. ORM-level deletion emits
        per-table DELETEs in an order that can strand a plugin FK — e.g.
        ``subscription_addon_subscription.invoice_id`` still referencing a
        ``vbwd_user_invoice`` row the ORM has already tried to delete, raising
        a ForeignKeyViolation.

        A single ``DELETE FROM vbwd_user WHERE id = :id`` lets Postgres resolve
        the whole cascade graph in one statement (NO ACTION checks run at
        statement end, after cascaded children are gone), which succeeds where
        the ORM ordering fails. This keeps core agnostic: it names no plugin
        table and relies purely on the DB cascade plugins declare in their own
        migrations.
        """
        result = self._session.execute(
            sa_delete(User).where(User.id == id)
        )
        self._session.commit()
        return result.rowcount > 0

    def find_by_email(self, email: str) -> Optional[User]:
        """Find user by email address."""
        return self._session.query(User).filter(User.email == email).first()

    def find_by_status(self, status: str) -> List[User]:
        """Find users by status."""
        return self._session.query(User).filter(User.status == status).all()

    def find_by_role(self, role: Union[UserRole, str]) -> List[User]:
        """Find all users holding the given role."""
        role_enum = role if isinstance(role, UserRole) else UserRole(role)
        return self._session.query(User).filter(User.role == role_enum).all()

    def email_exists(self, email: str) -> bool:
        """Check if email is already registered."""
        return self._session.query(User).filter(User.email == email).count() > 0

    def find_all_paginated(
        self,
        limit: int = 20,
        offset: int = 0,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[User], int]:
        """
        Find all users with pagination and filters.

        Args:
            limit: Maximum number of results.
            offset: Number of results to skip.
            status: Optional status filter.
            search: Optional email search string.

        Returns:
            Tuple of (users list, total count).
        """
        query = self._session.query(User)

        # Apply status filter
        if status:
            try:
                status_enum = UserStatus(status)
                query = query.filter(User.status == status_enum)
            except ValueError:
                pass

        # Apply search filter
        if search:
            query = query.filter(User.email.ilike(f"%{search}%"))

        # Get total count before pagination
        total = query.count()

        # Apply pagination
        users = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()

        return users, total
