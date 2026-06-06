"""Registry of invoice extra-field providers (plugin-contributed).

Core's ``GET /admin/invoices/<id>`` returns the invoice as a dict. Plugins
may attach extra, domain-specific detail keys to that response (e.g. the
subscription plugin adds plan/subscription metadata). Core merges each
provider's returned **opaque dict** into the response without ever reading a
key, so core names no plugin domain. With nothing registered (the contributing
plugin disabled) the invoice response carries only its core fields.

Mirrors ``deletion_dependency_registry``: a generic seam where core routes a
generic question and forwards an answer it never interprets.
"""
from typing import Any, Callable, Dict

# A provider maps an invoice to an opaque {key: value} dict of extra fields.
InvoiceExtraFieldsProvider = Callable[[Any], Dict[str, Any]]

_providers: Dict[str, InvoiceExtraFieldsProvider] = {}


def register_invoice_extra_fields_provider(
    key: str, provider: InvoiceExtraFieldsProvider
) -> None:
    """Register (or replace) a plugin's invoice extra-fields provider."""
    _providers[key] = provider


def unregister_invoice_extra_fields_provider(key: str) -> None:
    """Remove a plugin's provider (plugin disable)."""
    _providers.pop(key, None)


def clear_invoice_extra_fields_providers() -> None:
    """Reset all providers (test teardown)."""
    _providers.clear()


def aggregate_invoice_extra_fields(invoice: Any) -> Dict[str, Any]:
    """Merge the opaque extra-field dicts from all providers into one dict."""
    extra_fields: Dict[str, Any] = {}
    for provider in _providers.values():
        extra_fields.update(provider(invoice))
    return extra_fields
