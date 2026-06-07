"""User repository implementation."""
from typing import Optional, List, Tuple, Union
from vbwd.repositories.base import BaseRepository
from vbwd.models import User
from vbwd.models.enums import UserRole, UserStatus


class UserRepository(BaseRepository[User]):
    """Repository for User entity operations."""

    def __init__(self, session):
        super().__init__(session=session, model=User)

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
