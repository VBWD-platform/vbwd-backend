"""UserInvoice domain model."""
from vbwd.utils.datetime_utils import utcnow
import uuid
from sqlalchemy.dialects.postgresql import UUID, JSONB
from vbwd.extensions import db
from vbwd.models.base import BaseModel
from vbwd.models.enums import InvoiceStatus


class UserInvoice(BaseModel):
    """
    User invoice model.

    Tracks payment records for subscriptions.
    """

    __tablename__ = "vbwd_user_invoice"

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_number = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="EUR")
    status = db.Column(
        db.Enum(
            InvoiceStatus,
            name="invoicestatus",
            native_enum=True,
            create_constraint=False,
        ),
        nullable=False,
        default=InvoiceStatus.PENDING,
        index=True,
    )
    payment_method = db.Column(db.String(50))  # "stripe", "paypal", "basic", etc.
    payment_ref = db.Column(db.String(255))  # External payment reference
    subtotal = db.Column(db.Numeric(10, 2), nullable=True)  # Before tax
    tax_amount = db.Column(db.Numeric(10, 2), nullable=True, default=0)
    total_amount = db.Column(db.Numeric(10, 2), nullable=True)  # After tax
    invoiced_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utcnow,
    )
    paid_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)
    provider_session_id = db.Column(
        db.String(255), unique=True, nullable=True, index=True
    )
    payment_intent_id = db.Column(db.String(255), nullable=True, index=True)
    # Free-form JSON, written by payment plugins under their own top-level key
    # (e.g. ``{"stripe": {"transaction_id": "..."}, "tokens_paid": {"amount": 600}}``)
    # so the invoice detail can render plugin-specific captured-payment info
    # without core knowing any method's shape. Python attribute name differs
    # from the column name to avoid SQLAlchemy's ``metadata`` reserved attribute.
    # JSONB (not JSON): Postgres has no equality operator for ``json``, so any
    # ``SELECT DISTINCT`` involving this table (e.g. admin subscription detail
    # joining invoices via line items) throws "could not identify an equality
    # operator for type json". JSONB has the operator and is also faster to
    # query, so it's the right default here.
    payment_metadata = db.Column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    line_items = db.relationship(
        "InvoiceLineItem",
        backref="invoice",
        lazy="joined",
        cascade="all, delete-orphan",
    )

    @property
    def is_payable(self) -> bool:
        """Check if invoice can still be paid."""
        if self.status not in [InvoiceStatus.PENDING, InvoiceStatus.AUTHORIZED]:
            return False
        if self.expires_at and self.expires_at < utcnow():
            return False
        return True

    @property
    def is_capturable(self) -> bool:
        """Check if invoice has an authorized payment that can be captured."""
        return self.status == InvoiceStatus.AUTHORIZED

    def mark_authorized(
        self,
        payment_ref: str,
        payment_method: str,
    ) -> None:
        """Mark invoice as authorized (funds held, not yet captured)."""
        self.status = InvoiceStatus.AUTHORIZED
        self.payment_ref = payment_ref
        self.payment_method = payment_method

    def mark_paid(
        self,
        payment_ref: str,
        payment_method: str,
    ) -> None:
        """
        Mark invoice as paid.

        Args:
            payment_ref: External payment reference ID.
            payment_method: Payment provider used.
        """
        self.status = InvoiceStatus.PAID
        self.payment_ref = payment_ref
        self.payment_method = payment_method
        self.paid_at = utcnow()

    def mark_failed(self) -> None:
        """Mark invoice payment as failed."""
        self.status = InvoiceStatus.FAILED

    def mark_cancelled(self) -> None:
        """Mark invoice as cancelled."""
        self.status = InvoiceStatus.CANCELLED

    def mark_refunded(self) -> None:
        """Mark invoice as refunded."""
        self.status = InvoiceStatus.REFUNDED

    @staticmethod
    def generate_invoice_number() -> str:
        """Generate unique invoice number."""
        timestamp = utcnow().strftime("%Y%m%d%H%M%S")
        unique = uuid.uuid4().hex[:6].upper()
        return f"INV-{timestamp}-{unique}"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "invoice_number": self.invoice_number,
            "amount": str(self.amount),
            "subtotal": str(self.subtotal) if self.subtotal else str(self.amount),
            "tax_amount": str(self.tax_amount) if self.tax_amount else "0.00",
            "total_amount": str(self.total_amount)
            if self.total_amount
            else str(self.amount),
            "currency": self.currency,
            "status": self.status.value,
            "payment_method": self.payment_method,
            "payment_ref": self.payment_ref,
            "is_payable": self.is_payable,
            "is_capturable": self.is_capturable,
            "payment_intent_id": self.payment_intent_id,
            "line_items": [item.to_dict() for item in self.line_items]  # type: ignore[attr-defined]
            if self.line_items
            else [],
            "invoiced_at": self.invoiced_at.isoformat() if self.invoiced_at else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.payment_metadata or {},
        }

    def __repr__(self) -> str:
        return (
            f"<UserInvoice(number='{self.invoice_number}', status={self.status.value})>"
        )
