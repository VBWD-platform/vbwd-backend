"""Token balance and transaction repository."""
from typing import Optional, List
from uuid import UUID
from vbwd.repositories.base import BaseRepository
from vbwd.models.user_token_balance import UserTokenBalance, TokenTransaction


class TokenBalanceRepository(BaseRepository[UserTokenBalance]):
    """Repository for user token balances."""

    def __init__(self, session):
        super().__init__(session, UserTokenBalance)

    def find_by_user_id(self, user_id: UUID) -> Optional[UserTokenBalance]:
        """Find balance by user ID."""
        return (
            self._session.query(self._model)
            .filter(self._model.user_id == user_id)
            .first()
        )

    def get_or_create(self, user_id: UUID) -> UserTokenBalance:
        """Get existing balance or create new one with zero balance.

        Flush-only, never committed (S138.0): the zero row belongs to the
        caller's unit of work, so a movement that later rolls back does not
        leave an orphan balance behind. ``TokenService`` — the only caller —
        owns the commit.
        """
        balance = self.find_by_user_id(user_id)
        if not balance:
            balance = UserTokenBalance(user_id=user_id, balance=0)
            self._session.add(balance)
            self._session.flush()
        return balance


class TokenTransactionRepository(BaseRepository[TokenTransaction]):
    """Repository for token transactions."""

    def __init__(self, session):
        super().__init__(session, TokenTransaction)

    def find_by_user_id(
        self, user_id: UUID, limit: int = 50, offset: int = 0
    ) -> List[TokenTransaction]:
        """Find transactions by user ID."""
        return (
            self._session.query(self._model)
            .filter(self._model.user_id == user_id)
            .order_by(self._model.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def find_by_reference_id(self, reference_id: UUID) -> Optional[TokenTransaction]:
        """Find transaction by reference ID."""
        return (
            self._session.query(self._model)
            .filter(self._model.reference_id == reference_id)
            .first()
        )

    def create(self, transaction: TokenTransaction) -> TokenTransaction:
        """Create a new transaction."""
        return self.save(transaction)
