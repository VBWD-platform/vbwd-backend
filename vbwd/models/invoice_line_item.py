"""InvoiceLineItem domain model."""
from sqlalchemy.dialects.postgresql import JSONB, UUID
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

    __tablename__ = "vbwd_invoice_line_item"

    invoice_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_user_invoice.id", ondelete="CASCADE"),
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
    total_price = db.Column(db.Numeric(10, 2), nullable=False)  # gross
    # S85.4: first-class per-line tax disclosure. ``net_amount`` + ``tax_amount``
    # are the recorded netto / Σtax split for the charged gross (``total_price``);
    # ``tax_breakdown`` holds the per-rate lines ``[{"code","rate","amount"}]``
    # from the core ``Price`` VO. Generic JSONB the plugins populate — core stays
    # agnostic (no plugin model is imported here). Rounding to cents happens at
    # the plugin invoice-creation boundary, the one legitimate place (D4/D8).
    net_amount = db.Column(db.Numeric(10, 2), nullable=True)
    tax_amount = db.Column(db.Numeric(10, 2), nullable=True, default=0)
    tax_breakdown = db.Column(JSONB, nullable=True, default=list)
    extra_data = db.Column("metadata", db.JSON, nullable=True, default=dict)

    def _resolve_catalog_item_id(self) -> str | None:
        """Resolve the catalog item id via the line-item handler registry.

        Core no longer knows subscription/token specifics — each owner
        (token economy = core handler, subscription = plugin handler)
        resolves its own types.
        """
        from vbwd.events.line_item_registry import line_item_registry

        try:
            return line_item_registry.resolve_catalog_item_id(self)
        except Exception as resolve_error:  # noqa: BLE001 — registry contract
            # S24 — narrow this when the registry contract is tightened. For
            # now, any handler exception is swallowed (must not break the
            # to_dict serialisation path), but we log so debugging is possible.
            import logging

            logging.getLogger(__name__).warning(
                "resolve_catalog_item_id failed for line item %s: %s",
                getattr(self, "id", "<no-id>"),
                resolve_error,
            )
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
            # S85.4: per-line tax disclosure. Net falls back to the gross when
            # absent (taxless / legacy line); tax defaults to 0; breakdown to [].
            "net_amount": str(self.net_amount)
            if self.net_amount is not None
            else str(self.total_price),
            "tax_amount": str(self.tax_amount)
            if self.tax_amount is not None
            else "0.00",
            "tax_breakdown": self.tax_breakdown or [],
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
