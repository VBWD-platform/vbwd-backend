"""User token balance and transaction models."""
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel
from vbwd.models.enums import TokenTransactionType


class UserTokenBalance(BaseModel):
    """
    User token balance model.

    Tracks the current token balance for each user.
    Balance is updated via TokenTransaction records.
    """

    __tablename__ = "vbwd_user_token_balance"

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    balance = db.Column(db.Integer, nullable=False, default=0)

    # Relationship
    user = db.relationship("User", backref=db.backref("token_balance", uselist=False))

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "balance": self.balance,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<UserTokenBalance(user_id={self.user_id}, balance={self.balance})>"


class TokenTransaction(BaseModel):
    """
    Token transaction model.

    Records all token balance changes for audit trail.
    Positive amounts are credits, negative are debits.
    """

    __tablename__ = "vbwd_token_transaction"

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount = db.Column(db.Integer, nullable=False)  # positive=credit, negative=debit
    transaction_type = db.Column(
        db.Enum(
            TokenTransactionType,
            name="tokentransactiontype",
            native_enum=True,
            create_constraint=False,
        ),
        nullable=False,
    )
    reference_id = db.Column(UUID(as_uuid=True), nullable=True, index=True)
    description = db.Column(db.String(255), nullable=True)

    # Relationship
    user = db.relationship(
        "User", backref=db.backref("token_transactions", lazy="dynamic")
    )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "amount": self.amount,
            "transaction_type": self.transaction_type.value
            if self.transaction_type
            else None,
            "reference_id": str(self.reference_id) if self.reference_id else None,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<TokenTransaction(user_id={self.user_id}, amount={self.amount}, type={self.transaction_type})>"
