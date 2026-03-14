"""Token balance and transaction service."""
from src.utils.datetime_utils import utcnow
from typing import List, Optional
from uuid import UUID, uuid4
from src.models.user_token_balance import UserTokenBalance, TokenTransaction
from src.models.enums import TokenTransactionType, PurchaseStatus
from src.repositories.token_repository import (
    TokenBalanceRepository,
    TokenTransactionRepository,
)
from src.repositories.token_bundle_purchase_repository import (
    TokenBundlePurchaseRepository,
)


class TokenService:
    """Service for managing user token balances and transactions."""

    def __init__(
        self,
        balance_repo: TokenBalanceRepository,
        transaction_repo: TokenTransactionRepository,
        purchase_repo: TokenBundlePurchaseRepository,
    ):
        self._balance_repo = balance_repo
        self._transaction_repo = transaction_repo
        self._purchase_repo = purchase_repo

    def get_balance(self, user_id: UUID) -> int:
        """Get user's current token balance."""
        balance = self._balance_repo.find_by_user_id(user_id)
        return balance.balance if balance else 0

    def get_balance_object(self, user_id: UUID) -> Optional[UserTokenBalance]:
        """Get user's token balance object."""
        return self._balance_repo.find_by_user_id(user_id)

    def credit_tokens(
        self,
        user_id: UUID,
        amount: int,
        transaction_type: TokenTransactionType,
        reference_id: Optional[UUID] = None,
        description: Optional[str] = None,
    ) -> UserTokenBalance:
        """
        Credit tokens to user balance.

        Args:
            user_id: User ID
            amount: Number of tokens to credit (positive)
            transaction_type: Type of transaction
            reference_id: Optional reference (e.g., purchase ID)
            description: Optional description

        Returns:
            Updated UserTokenBalance
        """
        if amount <= 0:
            raise ValueError("Credit amount must be positive")

        # Get or create balance
        balance = self._balance_repo.get_or_create(user_id)
        balance.balance += amount
        self._balance_repo.save(balance)

        # Record transaction
        transaction = TokenTransaction(
            id=uuid4(),
            user_id=user_id,
            amount=amount,
            transaction_type=transaction_type,
            reference_id=reference_id,
            description=description,
        )
        self._transaction_repo.create(transaction)

        return balance

    def debit_tokens(
        self,
        user_id: UUID,
        amount: int,
        transaction_type: TokenTransactionType,
        reference_id: Optional[UUID] = None,
        description: Optional[str] = None,
    ) -> UserTokenBalance:
        """
        Debit tokens from user balance.

        Args:
            user_id: User ID
            amount: Number of tokens to debit (positive, will be stored as negative)
            transaction_type: Type of transaction
            reference_id: Optional reference
            description: Optional description

        Returns:
            Updated UserTokenBalance

        Raises:
            ValueError: If insufficient balance
        """
        if amount <= 0:
            raise ValueError("Debit amount must be positive")

        balance = self._balance_repo.find_by_user_id(user_id)
        if not balance or balance.balance < amount:
            raise ValueError("Insufficient token balance")

        balance.balance -= amount
        self._balance_repo.save(balance)

        # Record transaction with negative amount
        transaction = TokenTransaction(
            id=uuid4(),
            user_id=user_id,
            amount=-amount,
            transaction_type=transaction_type,
            reference_id=reference_id,
            description=description,
        )
        self._transaction_repo.create(transaction)

        return balance

    def complete_purchase(self, purchase_id: UUID) -> None:
        """
        Complete a token bundle purchase.

        Marks purchase as completed and credits tokens.

        Args:
            purchase_id: Token bundle purchase ID
        """
        purchase = self._purchase_repo.find_by_id(purchase_id)
        if not purchase:
            raise ValueError(f"Purchase {purchase_id} not found")

        if purchase.status != PurchaseStatus.PENDING:
            raise ValueError(f"Purchase {purchase_id} is not pending")

        # Mark as completed
        purchase.status = PurchaseStatus.COMPLETED
        purchase.completed_at = utcnow()
        purchase.tokens_credited = True
        self._purchase_repo.save(purchase)

        # Credit tokens
        self.credit_tokens(
            user_id=purchase.user_id,
            amount=purchase.token_amount,
            transaction_type=TokenTransactionType.PURCHASE,
            reference_id=purchase_id,
            description=f"Token bundle purchase: {purchase.token_amount} tokens",
        )

    def refund_tokens(
        self,
        user_id: UUID,
        amount: int,
        reference_id: Optional[UUID] = None,
        description: Optional[str] = None,
    ) -> int:
        """
        Debit tokens for a refund, clamping to 0 if balance insufficient.

        Returns actual amount debited.
        """
        balance = self._balance_repo.find_by_user_id(user_id)
        if not balance or balance.balance <= 0:
            return 0

        actual_debit = min(amount, balance.balance)
        balance.balance -= actual_debit
        self._balance_repo.save(balance)

        transaction = TokenTransaction(
            id=uuid4(),
            user_id=user_id,
            amount=-actual_debit,
            transaction_type=TokenTransactionType.REFUND,
            reference_id=reference_id,
            description=description,
        )
        self._transaction_repo.create(transaction)

        return actual_debit

    def get_transactions(
        self, user_id: UUID, limit: int = 50, offset: int = 0
    ) -> List[TokenTransaction]:
        """Get user's token transactions."""
        return self._transaction_repo.find_by_user_id(user_id, limit, offset)
