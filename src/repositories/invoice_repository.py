"""Invoice repository implementation."""
from typing import Optional, List, Union, Tuple
from uuid import UUID
from src.utils.datetime_utils import utcnow
from src.repositories.base import BaseRepository
from src.models import UserInvoice, InvoiceStatus


class InvoiceRepository(BaseRepository[UserInvoice]):
    """Repository for UserInvoice entity operations."""

    def __init__(self, session):
        super().__init__(session=session, model=UserInvoice)

    def find_by_user(self, user_id: Union[UUID, str]) -> List[UserInvoice]:
        """Find all invoices for a user."""
        return (
            self._session.query(UserInvoice)
            .filter(UserInvoice.user_id == user_id)
            .order_by(UserInvoice.created_at.desc())
            .all()
        )

    def find_by_invoice_number(self, invoice_number: str) -> Optional[UserInvoice]:
        """Find invoice by invoice number."""
        return (
            self._session.query(UserInvoice)
            .filter(UserInvoice.invoice_number == invoice_number)
            .first()
        )

    def find_by_subscription(
        self, subscription_id: Union[UUID, str]
    ) -> List[UserInvoice]:
        """Find all invoices for a subscription."""
        return (
            self._session.query(UserInvoice)
            .filter(UserInvoice.subscription_id == subscription_id)
            .order_by(UserInvoice.created_at.desc())
            .all()
        )

    def find_by_provider_session_id(
        self, provider_session_id: str
    ) -> Optional[UserInvoice]:
        """Find invoice by external provider session/order ID."""
        return (
            self._session.query(UserInvoice)
            .filter(UserInvoice.provider_session_id == provider_session_id)
            .first()
        )

    def find_pending(self) -> List[UserInvoice]:
        """Find all pending invoices."""
        return (
            self._session.query(UserInvoice)
            .filter(UserInvoice.status == InvoiceStatus.PENDING)
            .all()
        )

    def find_unpaid_by_user(self, user_id: Union[UUID, str]) -> List[UserInvoice]:
        """Find unpaid invoices for a user."""
        return (
            self._session.query(UserInvoice)
            .filter(
                UserInvoice.user_id == user_id,
                UserInvoice.status == InvoiceStatus.PENDING,
            )
            .order_by(UserInvoice.created_at.desc())
            .all()
        )

    def find_overdue(self) -> List[UserInvoice]:
        """Find invoices past due date."""
        return (
            self._session.query(UserInvoice)
            .filter(
                UserInvoice.status == InvoiceStatus.PENDING,
                UserInvoice.expires_at < utcnow(),
            )
            .order_by(UserInvoice.expires_at.asc())
            .all()
        )

    def find_all_paginated(
        self,
        limit: int = 20,
        offset: int = 0,
        status: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[UserInvoice], int]:
        """
        Find all invoices with pagination and filters.

        Args:
            limit: Maximum number of results.
            offset: Number of results to skip.
            status: Optional status filter.
            user_id: Optional user_id filter.

        Returns:
            Tuple of (invoices list, total count).
        """
        query = self._session.query(UserInvoice)

        # Apply status filter
        if status:
            try:
                status_enum = InvoiceStatus(status)
                query = query.filter(UserInvoice.status == status_enum)
            except ValueError:
                pass

        # Apply user filter
        if user_id:
            query = query.filter(UserInvoice.user_id == user_id)

        # Get total count before pagination
        total = query.count()

        # Apply pagination
        invoices = (
            query.order_by(UserInvoice.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return invoices, total
