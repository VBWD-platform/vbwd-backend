"""TokenBundle domain model."""
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class TokenBundle(BaseModel):
    """
    Token bundle model.

    Represents purchasable token packages that users can buy
    to add tokens to their account balance.

    Uses system default currency for pricing.
    """

    __tablename__ = "vbwd_token_bundle"

    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    token_amount = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)  # In default currency
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    sort_order = db.Column(db.Integer, default=0)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "token_amount": self.token_amount,
            "price": str(self.price),
            "is_active": self.is_active,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<TokenBundle(name='{self.name}', tokens={self.token_amount}, price={self.price})>"
