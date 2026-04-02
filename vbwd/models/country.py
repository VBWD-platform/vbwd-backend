"""Country model for billing address configuration."""
from sqlalchemy import Column, String, Boolean, Integer
from vbwd.models.base import BaseModel


class Country(BaseModel):
    """
    Country configuration for billing address selection.

    Admins can enable/disable countries and set display order.
    Only enabled countries are shown in checkout.
    """

    __tablename__ = "vbwd_country"

    code = Column(
        String(2), unique=True, nullable=False, index=True
    )  # ISO 3166-1 alpha-2
    name = Column(String(100), nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=False, index=True)
    position = Column(Integer, nullable=False, default=999)  # Display order

    def to_dict(self) -> dict:
        """Return full dictionary for admin view."""
        return {
            "id": str(self.id),
            "code": self.code,
            "name": self.name,
            "is_enabled": self.is_enabled,
            "position": self.position,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_public_dict(self) -> dict:
        """Return minimal dictionary for public/checkout view."""
        return {
            "code": self.code,
            "name": self.name,
        }

    def __repr__(self) -> str:
        return f"<Country {self.code} ({self.name})>"
