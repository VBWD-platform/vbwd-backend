"""Invoice line-item tags/custom-fields snapshot (S77).

An invoice is a historical document: the source product/plan's tags &
custom-fields may change after billing. So at line-item creation the issuer
**freezes** a copy of the source item's tags/CF onto the ``invoice_line_item``
id; the invoice serializer later reads that frozen copy, never the live source.

This is a pure ``(entity_type, id)`` value copy through the core port — no
plugin import. The *source* ``entity_type`` is known only to the plugin that
owns the line item, so it is resolved through the line-item handler registry
(``resolve_catalog_entity_ref``). Core orchestrates the copy; plugins supply
the source ref. Each plugin's invoice-creation path calls this single helper
after creating a line item, so the freeze logic has exactly one home (DRY).
"""
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

LINE_ITEM_ENTITY_TYPE = "invoice_line_item"


def snapshot_line_item_tags_and_custom_fields(line_item) -> None:
    """Freeze the source item's tags & custom-fields onto ``line_item``.

    No-op when the line item has no resolvable source entity, when the source
    carries no tags/CF, or when the framework path is unavailable. Never raises
    — a snapshot failure must not abort invoice creation.
    """
    from vbwd.events.line_item_registry import line_item_registry
    from vbwd.services.entity_type_registry import is_registered
    from vbwd.services.tags_and_custom_fields import resolve_tags_and_custom_fields

    if not is_registered(LINE_ITEM_ENTITY_TYPE):
        # invoice_line_item not registered (framework path disabled) — nothing
        # to freeze onto.
        return

    try:
        source_ref = line_item_registry.resolve_catalog_entity_ref(line_item)
    except Exception as resolve_error:
        logger.warning(
            "snapshot: resolve_catalog_entity_ref failed for line item %s: %s",
            getattr(line_item, "id", "<no-id>"),
            resolve_error,
        )
        return

    if source_ref is None:
        return
    source_entity_type, raw_source_id = source_ref
    if not is_registered(source_entity_type):
        return
    source_id = (
        raw_source_id if isinstance(raw_source_id, UUID) else UUID(str(raw_source_id))
    )

    port = resolve_tags_and_custom_fields()
    try:
        source_tags = port.get_tags(source_entity_type, source_id)
        source_fields = port.get_custom_fields(source_entity_type, source_id)
        if source_tags:
            port.set_tags(LINE_ITEM_ENTITY_TYPE, line_item.id, source_tags)
        if source_fields:
            port.set_custom_fields(LINE_ITEM_ENTITY_TYPE, line_item.id, source_fields)
    except Exception as snapshot_error:
        logger.warning(
            "snapshot: freezing tags/custom-fields failed for line item %s "
            "(source %s/%s): %s",
            getattr(line_item, "id", "<no-id>"),
            source_entity_type,
            source_id,
            snapshot_error,
        )
