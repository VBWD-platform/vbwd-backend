"""TokenBundlePurchase repository implementation."""
from typing import List
from uuid import UUID
from vbwd.repositories.base import BaseRepository
from vbwd.models.token_bundle_purchase import TokenBundlePurchase
from vbwd.models.enums import PurchaseStatus


class TokenBundlePurchaseRepository(BaseRepository[TokenBundlePurchase]):
    """Repository for TokenBundlePurchase entity operations."""

    def __init__(self, session):
        super().__init__(session=session, model=TokenBundlePurchase)

    def find_by_user(self, user_id: UUID) -> List[TokenBundlePurchase]:
        """Find all purchases for a user."""
        return (
            self._session.query(TokenBundlePurchase)
            .filter(TokenBundlePurchase.user_id == user_id)
            .order_by(TokenBundlePurchase.created_at.desc())
            .all()
        )

    def find_by_invoice(self, invoice_id: UUID) -> List[TokenBundlePurchase]:
        """Find all purchases for an invoice."""
        return (
            self._session.query(TokenBundlePurchase)
            .filter(TokenBundlePurchase.invoice_id == invoice_id)
            .all()
        )

    def count_by_bundle(self, bundle_id: UUID) -> int:
        """Count purchases that reference a given token bundle.

        Used to guard bundle deletion: a bundle with purchase history must not
        be hard-deleted (it would orphan financial records).
        """
        return (
            self._session.query(TokenBundlePurchase)
            .filter(TokenBundlePurchase.bundle_id == bundle_id)
            .count()
        )

    def find_pending_by_user(self, user_id: UUID) -> List[TokenBundlePurchase]:
        """Find all pending purchases for a user."""
        return (
            self._session.query(TokenBundlePurchase)
            .filter(
                TokenBundlePurchase.user_id == user_id,
                TokenBundlePurchase.status == PurchaseStatus.PENDING,
            )
            .all()
        )

    def find_completed_uncredited(self) -> List[TokenBundlePurchase]:
        """Find completed purchases where tokens haven't been credited."""
        return (
            self._session.query(TokenBundlePurchase)
            .filter(
                TokenBundlePurchase.status == PurchaseStatus.COMPLETED,
                TokenBundlePurchase.tokens_credited.is_(False),
            )
            .all()
        )

    def create(self, purchase: TokenBundlePurchase) -> TokenBundlePurchase:
        """Create a new purchase."""
        self._session.add(purchase)
        self._session.commit()
        self._session.refresh(purchase)
        return purchase
