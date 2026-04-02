"""TokenBundlePurchase domain model."""
from vbwd.utils.datetime_utils import utcnow
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel
from vbwd.models.enums import PurchaseStatus


class TokenBundlePurchase(BaseModel):
    """
    Token bundle purchase model.

    Tracks user purchases of token bundles.
    Status is PENDING until payment is confirmed.
    """

    __tablename__ = "vbwd_token_bundle_purchase"

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bundle_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_token_bundle.id"),
        nullable=False,
        index=True,
    )
    invoice_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_user_invoice.id"),
        nullable=True,
        index=True,
    )
    status = db.Column(
        db.Enum(
            PurchaseStatus,
            name="purchasestatus",
            native_enum=True,
            create_constraint=False,
        ),
        nullable=False,
        default=PurchaseStatus.PENDING,
        index=True,
    )
    tokens_credited = db.Column(db.Boolean, nullable=False, default=False)
    token_amount = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    bundle = db.relationship(
        "TokenBundle",
        backref="purchases",
        lazy="joined",
    )

    def complete(self) -> None:
        """Mark purchase as completed."""
        self.status = PurchaseStatus.COMPLETED
        self.completed_at = utcnow()

    def credit_tokens(self) -> None:
        """Mark tokens as credited to user."""
        self.tokens_credited = True

    def refund(self) -> None:
        """Mark purchase as refunded."""
        self.status = PurchaseStatus.REFUNDED

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "bundle_id": str(self.bundle_id),
            "invoice_id": str(self.invoice_id) if self.invoice_id else None,
            "status": self.status.value,
            "tokens_credited": self.tokens_credited,
            "token_amount": self.token_amount,
            "price": str(self.price),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
        }

    def __repr__(self) -> str:
        return f"<TokenBundlePurchase(bundle_id={self.bundle_id}, status={self.status.value})>"
