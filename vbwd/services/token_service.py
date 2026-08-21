"""Token balance and transaction service."""
from vbwd.utils.datetime_utils import utcnow
from typing import List, Optional
from uuid import UUID, uuid4
from vbwd.events import event_bus
from vbwd.models.user_token_balance import UserTokenBalance, TokenTransaction
from vbwd.models.enums import TokenTransactionType, PurchaseStatus
from vbwd.repositories.token_repository import (
    TokenBalanceRepository,
    TokenTransactionRepository,
)
from vbwd.repositories.token_bundle_purchase_repository import (
    TokenBundlePurchaseRepository,
)
from vbwd.services.token_balance_hooks import TokenMovement, run_token_movement_hooks


def _require_whole_token_amount(amount: int) -> None:
    """Reject anything that is not a plain ``int`` number of tokens.

    ``amount: int`` used to be an annotation only: ``2.5`` passed the
    ``amount <= 0`` guard, reached the ``db.Integer`` column and Postgres
    silently rounded it, so the caller moved a different number of tokens than
    it asked for. ``True`` is an ``int`` to Python and quietly credited one
    token. Both are caller bugs, so this raises ``TypeError`` — never the
    ``ValueError`` that callers catch to mean "insufficient balance".
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError(
            f"Token amount must be a whole number of tokens, got {amount!r}"
        )


class TokenService:
    """Service for managing user token balances and transactions.

    Every balance change is ONE unit of work (S138.0): the balance row, its
    ``TokenTransaction`` and any registered token-movement hook's writes are
    flushed on the service's own session and committed together. Previously the
    balance and the transaction each committed through ``BaseRepository.save``,
    so a failure between them left a balance change with no ledger row.
    """

    def __init__(
        self,
        balance_repo: TokenBalanceRepository,
        transaction_repo: TokenTransactionRepository,
        purchase_repo: TokenBundlePurchaseRepository,
        session,
    ):
        self._balance_repo = balance_repo
        self._transaction_repo = transaction_repo
        self._purchase_repo = purchase_repo
        self._session = session

    def get_balance(self, user_id: UUID) -> int:
        """Get user's current token balance."""
        balance = self._balance_repo.find_by_user_id(user_id)
        return balance.balance if balance else 0

    def get_balance_object(self, user_id: UUID) -> Optional[UserTokenBalance]:
        """Get user's token balance object."""
        return self._balance_repo.find_by_user_id(user_id)

    def _apply_movement(
        self,
        balance: UserTokenBalance,
        user_id: UUID,
        delta: int,
        transaction_type: TokenTransactionType,
        reference_id: Optional[UUID],
        description: Optional[str],
        commit: bool = True,
    ) -> UserTokenBalance:
        """Apply a signed balance change as one atomic unit of work.

        The single home for every token movement (credit, debit, refund): it
        moves the balance, appends the matching ``TokenTransaction``, flushes
        both, runs the registered hooks on the still-open transaction, and only
        then commits. Anything raising — a hook included — rolls the whole unit
        back, so the balance can never move without its ledger row (or without
        a subscriber's mirror of it).

        ``delta`` is signed: positive credits, negative debits. Callers validate
        (whole positive amount, sufficient balance) BEFORE calling, so a
        rejected request never touches the caller's transaction.

        ``commit=False`` composes the movement into a caller's own transaction:
        the flush and the hooks still happen — so the caller's transaction sees
        the movement and a bookkeeper can still veto it — but the commit belongs
        to the caller. The rollback on failure applies to BOTH modes and is
        load-bearing either way: a flushed-but-vetoed mutation left pending
        would otherwise ride along on the caller's next commit.
        """
        try:
            balance.balance += delta
            transaction = TokenTransaction(
                id=uuid4(),
                user_id=user_id,
                amount=delta,
                transaction_type=transaction_type,
                reference_id=reference_id,
                description=description,
            )
            self._session.add(balance)
            self._session.add(transaction)
            self._session.flush()

            movement = TokenMovement(
                user_id=user_id,
                delta=delta,
                balance_after=balance.balance,
                transaction_type=transaction_type,
                reference_id=reference_id,
                description=description,
            )
            run_token_movement_hooks(movement, self._session)

            if commit:
                self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        if commit:
            self._publish_token_moved(movement)

        return balance

    def _publish_token_moved(self, movement: TokenMovement) -> None:
        """Announce a committed movement on the EventBus (best effort).

        For non-critical consumers only — notifications, analytics. The bus
        swallows subscriber exceptions, so a consumer that must not miss a
        movement registers a token-movement hook instead and gets the
        transaction.

        Only published once the movement is durable. A ``commit=False``
        movement's durability belongs to the caller, and core cannot know
        whether that caller went on to commit or roll back — announcing it here
        could report a movement that never happened, so the composing caller
        owns any event it needs. The hook fires either way, so nothing critical
        depends on this distinction.
        """
        event_bus.publish(
            "token.moved",
            {
                "user_id": str(movement.user_id),
                "delta": movement.delta,
                "balance_after": movement.balance_after,
                "transaction_type": movement.transaction_type.value,
                "reference_id": (
                    str(movement.reference_id) if movement.reference_id else None
                ),
            },
        )

    def credit_tokens(
        self,
        user_id: UUID,
        amount: int,
        transaction_type: TokenTransactionType,
        reference_id: Optional[UUID] = None,
        description: Optional[str] = None,
        commit: bool = True,
    ) -> UserTokenBalance:
        """
        Credit tokens to user balance.

        Args:
            user_id: User ID
            amount: Whole number of tokens to credit (positive)
            transaction_type: Type of transaction
            reference_id: Optional reference (e.g., purchase ID)
            description: Optional description
            commit: Commit the movement (default). Pass False to compose it into
                the caller's transaction — the caller then owns the commit.

        Returns:
            Updated UserTokenBalance

        Raises:
            TypeError: If amount is not a whole number of tokens
            ValueError: If amount is not positive
        """
        _require_whole_token_amount(amount)
        if amount <= 0:
            raise ValueError("Credit amount must be positive")

        balance = self._balance_repo.get_or_create(user_id)
        return self._apply_movement(
            balance=balance,
            user_id=user_id,
            delta=amount,
            transaction_type=transaction_type,
            reference_id=reference_id,
            description=description,
            commit=commit,
        )

    def debit_tokens(
        self,
        user_id: UUID,
        amount: int,
        transaction_type: TokenTransactionType,
        reference_id: Optional[UUID] = None,
        description: Optional[str] = None,
        commit: bool = True,
    ) -> UserTokenBalance:
        """
        Debit tokens from user balance.

        Args:
            user_id: User ID
            amount: Whole number of tokens to debit (positive, stored as negative)
            transaction_type: Type of transaction
            reference_id: Optional reference
            description: Optional description
            commit: Commit the movement (default). Pass False to compose it into
                the caller's transaction — the caller then owns the commit.

        Returns:
            Updated UserTokenBalance

        Raises:
            TypeError: If amount is not a whole number of tokens
            ValueError: If amount is not positive, or balance insufficient
        """
        _require_whole_token_amount(amount)
        if amount <= 0:
            raise ValueError("Debit amount must be positive")

        balance = self._balance_repo.find_by_user_id(user_id)
        if not balance or balance.balance < amount:
            raise ValueError("Insufficient token balance")

        return self._apply_movement(
            balance=balance,
            user_id=user_id,
            delta=-amount,
            transaction_type=transaction_type,
            reference_id=reference_id,
            description=description,
            commit=commit,
        )

    def complete_purchase(self, purchase_id: UUID) -> None:
        """
        Complete a token bundle purchase as ONE unit of work.

        Marks the purchase completed and credits the tokens under a single
        commit. It used to save the purchase through the repository — which
        commits — BEFORE crediting, so a credit that failed (or a hook that
        vetoed it) left the purchase durably COMPLETED with no tokens: a durable
        state change with no counterpart, the same hole as the double-commit.

        Args:
            purchase_id: Token bundle purchase ID
        """
        purchase = self._purchase_repo.find_by_id(purchase_id)
        if not purchase:
            raise ValueError(f"Purchase {purchase_id} not found")

        if purchase.status != PurchaseStatus.PENDING:
            raise ValueError(f"Purchase {purchase_id} is not pending")

        try:
            # Marked on the session, NOT saved through the repository: the
            # credit's own commit then makes the status and the tokens durable
            # together. The try/except still matters — ``credit_tokens``
            # validates before it opens its unit of work, and a rejection there
            # must not leave the COMPLETED status pending in the session.
            purchase.status = PurchaseStatus.COMPLETED
            purchase.completed_at = utcnow()
            purchase.tokens_credited = True
            self._session.add(purchase)

            self.credit_tokens(
                user_id=purchase.user_id,
                amount=purchase.token_amount,
                transaction_type=TokenTransactionType.PURCHASE,
                reference_id=purchase_id,
                description=f"Token bundle purchase: {purchase.token_amount} tokens",
            )
        except Exception:
            self._session.rollback()
            raise

    def refund_tokens(
        self,
        user_id: UUID,
        amount: int,
        reference_id: Optional[UUID] = None,
        description: Optional[str] = None,
        commit: bool = True,
    ) -> int:
        """
        Debit tokens for a refund, clamping to 0 if balance insufficient.

        Deliberately does NOT reuse ``debit_tokens``: a refund clamps to the
        available balance instead of raising. It shares the same unit of work,
        so it fires the token-movement hooks exactly like every other movement.

        Pass ``commit=False`` to compose the refund into the caller's
        transaction.

        Returns actual amount debited.
        """
        _require_whole_token_amount(amount)

        balance = self._balance_repo.find_by_user_id(user_id)
        if not balance or balance.balance <= 0:
            return 0

        actual_debit = min(amount, balance.balance)
        self._apply_movement(
            balance=balance,
            user_id=user_id,
            delta=-actual_debit,
            transaction_type=TokenTransactionType.REFUND,
            reference_id=reference_id,
            description=description,
            commit=commit,
        )

        return actual_debit

    def get_transactions(
        self, user_id: UUID, limit: int = 50, offset: int = 0
    ) -> List[TokenTransaction]:
        """Get user's token transactions."""
        return self._transaction_repo.find_by_user_id(user_id, limit, offset)
