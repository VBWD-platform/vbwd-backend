"""UserDetails domain model."""
from sqlalchemy.dialects.postgresql import UUID, JSONB
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class UserDetails(BaseModel):
    """
    User private details model.

    Separated from User for GDPR compliance.
    Contains PII that may need to be deleted separately.
    """

    __tablename__ = "vbwd_user_details"

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_user.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    address_line_1 = db.Column(db.String(255))
    address_line_2 = db.Column(db.String(255))
    city = db.Column(db.String(100))
    postal_code = db.Column(db.String(20))
    country = db.Column(db.String(2))  # ISO 3166-1 alpha-2
    phone = db.Column(db.String(20))

    # New fields for Sprint 03
    company = db.Column(db.String(255))
    tax_number = db.Column(db.String(100))
    config = db.Column(JSONB, default=dict)  # User preferences: language, theme, etc.
    balance = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)

    @property
    def full_name(self) -> str:
        """Get full name."""
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p)

    @property
    def full_address(self) -> str:
        """Get formatted full address."""
        lines = [
            self.address_line_1,
            self.address_line_2,
            f"{self.postal_code} {self.city}".strip(),
            self.country,
        ]
        return "\n".join(line for line in lines if line)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "address_line_1": self.address_line_1,
            "address_line_2": self.address_line_2,
            "city": self.city,
            "postal_code": self.postal_code,
            "country": self.country,
            "phone": self.phone,
            "company": self.company,
            "tax_number": self.tax_number,
            "config": self.config or {},
            "balance": float(self.balance) if self.balance is not None else 0.00,
        }

    def __repr__(self) -> str:
        return f"<UserDetails(user_id={self.user_id}, name='{self.full_name}')>"
