"""InvoiceLineItem domain model."""
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel
from vbwd.models.enums import LineItemType


class InvoiceLineItem(BaseModel):
    """
    Invoice line item model.

    Tracks individual items on an invoice (subscription, token bundle, add-on,
    or custom plugin items like bookings).
    item_id references the purchase record (subscription, token_bundle_purchase,
    addon_subscription, or plugin-specific record).
    catalog_item_id resolves to the actual catalog entity
    (tarif_plan, token_bundle, addon).
    """

    __tablename__ = "invoice_line_item"

    invoice_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("user_invoice.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_type = db.Column(
        db.Enum(
            LineItemType, name="lineitemtype", native_enum=True, create_constraint=False
        ),
        nullable=False,
    )
    item_id = db.Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    extra_data = db.Column("metadata", db.JSON, nullable=True, default=dict)

    def _resolve_catalog_item_id(self) -> str | None:
        """Resolve the catalog item ID from the purchase record."""
        from vbwd.models.subscription import Subscription
        from vbwd.models.token_bundle_purchase import TokenBundlePurchase
        from vbwd.models.addon_subscription import AddOnSubscription

        try:
            if self.item_type == LineItemType.SUBSCRIPTION:
                sub = db.session.get(Subscription, self.item_id)
                return str(sub.tarif_plan_id) if sub else None
            elif self.item_type == LineItemType.TOKEN_BUNDLE:
                purchase = db.session.get(TokenBundlePurchase, self.item_id)
                return str(purchase.bundle_id) if purchase else None
            elif self.item_type == LineItemType.ADD_ON:
                addon_sub = db.session.get(AddOnSubscription, self.item_id)
                return str(addon_sub.addon_id) if addon_sub else None
        except Exception:
            pass
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        # For CUSTOM items, use plugin name as display type if available
        display_type = self.item_type.value
        if self.item_type == LineItemType.CUSTOM and self.extra_data:
            plugin_name = self.extra_data.get("plugin")
            if plugin_name:
                display_type = plugin_name

        result = {
            "id": str(self.id),
            "invoice_id": str(self.invoice_id),
            "type": display_type,
            "item_id": str(self.item_id),
            "description": self.description,
            "quantity": self.quantity,
            "unit_price": str(self.unit_price),
            "amount": str(self.total_price),
        }
        catalog_id = self._resolve_catalog_item_id()
        if catalog_id:
            result["catalog_item_id"] = catalog_id
        if self.extra_data:
            result["metadata"] = self.extra_data
        return result

    def __repr__(self) -> str:
        return (
            f"<InvoiceLineItem(type={self.item_type.value}, amount={self.total_price})>"
        )
