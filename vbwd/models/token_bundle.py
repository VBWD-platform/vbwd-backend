"""TokenBundle domain model."""
from vbwd.extensions import db
from vbwd.models.base import BaseModel


# S85.1 (D6): CORE-to-CORE many-to-many join between token bundles and the
# CORE tax catalog (``vbwd_tax``), mirroring the S72.3 join-table shape so
# bundles carry a uniform ``taxes`` relationship like the plugin sellables.
# Both tables are core (the agnosticism oracle stays green). The ``tax_id`` FK
# uses ``ON DELETE RESTRICT`` so deleting a tax assigned to a bundle is rejected
# by the database rather than silently dropping the link; ``bundle_id`` uses
# ``ON DELETE CASCADE``.
token_bundle_tax = db.Table(
    "token_bundle_tax",
    db.Column(
        "bundle_id",
        db.UUID,
        db.ForeignKey("vbwd_token_bundle.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "tax_id",
        db.UUID,
        db.ForeignKey("vbwd_tax.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


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
    # S85.1 (D4): the single price double (full precision, never rounded in
    # code), in the global ``default_currency`` (S84).
    price = db.Column(db.Float, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    sort_order = db.Column(db.Integer, default=0)

    # Assigned core taxes (M2M, S85.1 / D6). Mirrors plan / product / resource.
    taxes = db.relationship(
        "Tax",
        secondary=token_bundle_tax,
        lazy="selectin",
    )

    @property
    def raw_price(self) -> float:
        """The stored price as a float (the ``Priceable`` protocol member)."""
        return float(self.price) if self.price is not None else 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary.

        S85.1 (D5): the single ``price`` double is the only stored money field.
        The computed ``Price`` value object is assembled at the route layer
        (S85.2), keeping the model thin.
        """
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "token_amount": self.token_amount,
            "price": self.raw_price,
            "is_active": self.is_active,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<TokenBundle(name='{self.name}', tokens={self.token_amount}, price={self.price})>"
