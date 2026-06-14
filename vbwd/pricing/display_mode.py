"""Resolve the netto/brutto display-mode pair for a sellable (S72.4, DRY).

This is the single home for the display-mode pair every sellable payload carries
so the fe-user consumer can pick net vs gross and render the "netto price" tag:

  * ``prices_display_mode``    — the global core setting.
  * ``effective_display_mode`` — the per-item ``price_display_mode`` override
    ?? the global mode.

It is a *display* concern only (orthogonal to ``prices_mode_in_db``, which is
how the stored double is interpreted). Core-only: it reads the core settings
store and a defensive ``getattr`` on the item — no plugin import.
"""
from typing import Any, Dict

from vbwd.services.core_settings_store import get_core_settings


def display_mode_fields(priceable: Any) -> Dict[str, str]:
    """Return ``{prices_display_mode, effective_display_mode}`` for a sellable.

    Args:
        priceable: Any sellable; its optional ``price_display_mode`` override is
            read defensively (objects lacking it fall back to the global mode).

    Returns:
        The global display mode plus the effective mode (override ?? global).
    """
    global_mode = get_core_settings()["prices_display_mode"]
    override = getattr(priceable, "price_display_mode", None)
    return {
        "prices_display_mode": global_mode,
        "effective_display_mode": override or global_mode,
    }
