"""S77 — line-item source entity-ref resolution (snapshot seam).

The invoice line-item snapshot needs both the source ``entity_type`` and its
catalog id. Each line-item handler knows its own source type, so the registry
exposes a context-free ``resolve_catalog_entity_ref(line_item) -> (type, id)``
pass-through, mirroring ``resolve_catalog_item_id``. Handlers that own no source
entity inherit the ``None`` default (ISP / Liskov-safe).
"""
from uuid import uuid4

from vbwd.events.line_item_registry import (
    ILineItemHandler,
    LineItemResult,
    LineItemHandlerRegistry,
)


class _NullHandler(ILineItemHandler):
    """Owns nothing — must inherit the None defaults (Liskov)."""

    def can_handle_line_item(self, line_item, context):
        return False

    def activate_line_item(self, line_item, context):
        return LineItemResult.skip()

    def reverse_line_item(self, line_item, context):
        return LineItemResult.skip()

    def restore_line_item(self, line_item, context):
        return LineItemResult.skip()


class _PlanHandler(ILineItemHandler):
    """Owns SUBSCRIPTION lines, sourced from a ``tarif_plan``."""

    def __init__(self, plan_id):
        self._plan_id = plan_id

    def can_handle_line_item(self, line_item, context):
        return getattr(line_item, "kind", None) == "subscription"

    def activate_line_item(self, line_item, context):
        return LineItemResult.skip()

    def reverse_line_item(self, line_item, context):
        return LineItemResult.skip()

    def restore_line_item(self, line_item, context):
        return LineItemResult.skip()

    def resolve_catalog_entity_ref(self, line_item):
        if getattr(line_item, "kind", None) != "subscription":
            return None
        return ("tarif_plan", self._plan_id)


class _LineItem:
    def __init__(self, kind):
        self.kind = kind
        self.id = uuid4()


def test_base_handler_entity_ref_defaults_to_none():
    handler = _NullHandler()
    assert handler.resolve_catalog_entity_ref(_LineItem("anything")) is None


def test_registry_returns_first_owning_handlers_ref():
    plan_id = str(uuid4())
    registry = LineItemHandlerRegistry()
    registry.register(_NullHandler())
    registry.register(_PlanHandler(plan_id))

    ref = registry.resolve_catalog_entity_ref(_LineItem("subscription"))
    assert ref == ("tarif_plan", plan_id)


def test_registry_returns_none_when_no_handler_owns_the_line():
    registry = LineItemHandlerRegistry()
    registry.register(_NullHandler())
    registry.register(_PlanHandler(str(uuid4())))

    assert registry.resolve_catalog_entity_ref(_LineItem("token_bundle")) is None


def test_registry_skips_handler_that_raises_and_continues():
    plan_id = str(uuid4())

    class _Boom(ILineItemHandler):
        def can_handle_line_item(self, line_item, context):
            return False

        def activate_line_item(self, line_item, context):
            return LineItemResult.skip()

        def reverse_line_item(self, line_item, context):
            return LineItemResult.skip()

        def restore_line_item(self, line_item, context):
            return LineItemResult.skip()

        def resolve_catalog_entity_ref(self, line_item):
            raise RuntimeError("handler blew up")

    registry = LineItemHandlerRegistry()
    registry.register(_Boom())
    registry.register(_PlanHandler(plan_id))

    ref = registry.resolve_catalog_entity_ref(_LineItem("subscription"))
    assert ref == ("tarif_plan", plan_id)
