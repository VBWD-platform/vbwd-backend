"""User-facing invoice routes."""
from datetime import datetime
from decimal import Decimal

from flask import Blueprint, Response, current_app, g, jsonify

from vbwd.middleware.auth import require_auth

invoices_bp = Blueprint("invoices", __name__, url_prefix="/api/v1/user/invoices")


def get_pdf_service():
    """Accessor for the DI-container-provided PdfService.

    Kept as a module-level function so tests can patch it and the route
    stays thin.
    """
    return current_app.container.pdf_service()  # type: ignore[attr-defined]


def _company_context() -> dict:
    """Company metadata for PDF headers — pulled from app config.

    Settings live in app.config keyed under COMPANY_*. Safe defaults keep
    the template renderable even on a bare dev environment.
    """
    config = current_app.config
    return {
        "name": config.get("COMPANY_NAME", "VBWD"),
        "tagline": config.get("COMPANY_TAGLINE", ""),
        "address": config.get("COMPANY_ADDRESS", ""),
        "email": config.get("COMPANY_EMAIL", ""),
        "website": config.get("COMPANY_WEBSITE", ""),
        "tax_id": config.get("COMPANY_TAX_ID", ""),
    }


def _format_money(amount, currency: str) -> str:
    if amount is None:
        return ""
    decimal_amount = Decimal(str(amount))
    return f"{decimal_amount:.2f} {currency}"


def _format_date(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _build_invoice_pdf_context(invoice, user) -> dict:
    """Shape the invoice into the flat dict the template expects."""
    currency = invoice.currency or "EUR"
    line_items = []
    for item in getattr(invoice, "line_items", []) or []:
        unit_price = getattr(item, "unit_price", None) or getattr(item, "amount", None)
        line_items.append(
            {
                "description": getattr(item, "description", "") or "",
                "quantity": getattr(item, "quantity", 1) or 1,
                "unit_price_display": _format_money(unit_price, currency),
                "total_display": _format_money(
                    getattr(item, "total", None) or getattr(item, "amount", None),
                    currency,
                ),
            }
        )

    subtotal = getattr(invoice, "subtotal", None)
    tax_amount = getattr(invoice, "tax_amount", None)
    total_amount = getattr(invoice, "total_amount", None) or invoice.amount

    customer_details = getattr(user, "details", None)
    customer_name = ""
    customer_company = ""
    customer_phone = ""
    customer_address = ""
    if customer_details is not None:
        first_name = getattr(customer_details, "first_name", "") or ""
        last_name = getattr(customer_details, "last_name", "") or ""
        customer_name = (first_name + " " + last_name).strip()
        customer_company = getattr(customer_details, "company", "") or ""
        customer_phone = getattr(customer_details, "phone", "") or ""
        customer_address = getattr(customer_details, "address", "") or ""

    return {
        "company": _company_context(),
        "customer": {
            "name": customer_name,
            "email": getattr(user, "email", "") or "",
            "company": customer_company,
            "phone": customer_phone,
            "address": customer_address,
        },
        "invoice": {
            "id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "status": invoice.status.value
            if hasattr(invoice.status, "value")
            else str(invoice.status),
            "issued_at_display": _format_date(getattr(invoice, "invoiced_at", None)),
            "due_date_display": _format_date(getattr(invoice, "expires_at", None)),
            "subtotal_display": _format_money(subtotal, currency) if subtotal else "",
            "tax_display": _format_money(tax_amount, currency)
            if tax_amount and Decimal(str(tax_amount)) > 0
            else "",
            "discount_display": "",
            "total_display": _format_money(total_amount, currency),
            "notes": getattr(invoice, "notes", "") or "",
        },
        "line_items": line_items,
    }


@invoices_bp.route("/", methods=["GET"])
@require_auth
def get_invoices():
    """
    List user's invoices.

    Returns:
        200: List of user's invoices
        401: If not authenticated
    """
    # S08 — pull service from container.
    invoice_service = current_app.container.invoice_service()
    invoices = invoice_service.get_user_invoices(str(g.user_id))
    return jsonify({"invoices": [inv.to_dict() for inv in invoices]}), 200


@invoices_bp.route("/<invoice_id>", methods=["GET"])
@require_auth
def get_invoice(invoice_id):
    """
    Get invoice detail.

    Returns:
        200: Invoice details
        401: If not authenticated
        403: If user doesn't own the invoice
        404: If invoice not found
    """
    # S08 — pull service from container.
    invoice_service = current_app.container.invoice_service()
    invoice = invoice_service.get_invoice(invoice_id)

    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404

    if str(invoice.user_id) != str(g.user_id):
        return jsonify({"error": "Access denied"}), 403

    return jsonify({"invoice": invoice.to_dict()}), 200


@invoices_bp.route("/<invoice_id>/pdf", methods=["GET"])
@require_auth
def download_invoice_pdf(invoice_id):
    """
    Download a PDF rendering of the invoice.

    Returns:
        200: application/pdf stream, Content-Disposition: attachment
        401: If not authenticated
        403: If user doesn't own the invoice
        404: If invoice not found
    """
    # S08 — pull service from container.
    invoice_service = current_app.container.invoice_service()
    invoice = invoice_service.get_invoice(invoice_id)

    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404

    if str(invoice.user_id) != str(g.user_id):
        return jsonify({"error": "Access denied"}), 403

    # Pull the authenticated user record to populate billing-party fields.
    user = getattr(g, "current_user", None)
    if user is None:
        # S08 — pull repo from container.
        user = current_app.container.user_repository().find_by_id(str(g.user_id))

    pdf_service = get_pdf_service()
    context = _build_invoice_pdf_context(invoice, user)
    pdf_bytes = pdf_service.render("invoice.html", context)

    filename = f"invoice-{invoice.invoice_number or invoice.id}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
