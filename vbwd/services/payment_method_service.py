"""PaymentMethodService — admin-side CRUD logic for PaymentMethod.

S23 — extracted from ``vbwd/routes/admin/payment_methods.py`` so the
route handlers are thin transport layers (deserialize → call service →
serialize) and the business logic is testable in isolation with a
mocked repository.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional

from vbwd.models import PaymentMethod


class PaymentMethodValidationError(ValueError):
    """Raised when the input payload fails domain-level validation."""


def _optional_decimal(payload: Mapping[str, Any], key: str) -> Optional[Decimal]:
    value = payload.get(key)
    return Decimal(str(value)) if value is not None else None


class PaymentMethodService:
    """Business logic for admin payment-method operations.

    The session is exposed so the service can clear the previous
    ``is_default`` flag in the same transaction as the insert. Future
    cleanup: move the "clear other defaults" operation into the repository.
    """

    def __init__(self, repository, session) -> None:
        self._repository = repository
        self._session = session

    def create(self, payload: Mapping[str, Any]) -> PaymentMethod:
        """Validate the payload and create a payment method.

        Raises:
            PaymentMethodValidationError: missing required field or duplicate code.
        """
        self._require(payload, "code")
        self._require(payload, "name")
        if self._repository.code_exists(payload["code"]):
            raise PaymentMethodValidationError("Code already exists")

        method = PaymentMethod(
            code=payload["code"],
            name=payload["name"],
            description=payload.get("description"),
            short_description=payload.get("short_description"),
            icon=payload.get("icon"),
            plugin_id=payload.get("plugin_id"),
            is_active=payload.get("is_active", True),
            is_default=payload.get("is_default", False),
            position=payload.get("position", 0),
            min_amount=_optional_decimal(payload, "min_amount"),
            max_amount=_optional_decimal(payload, "max_amount"),
            currencies=payload.get("currencies", []),
            countries=payload.get("countries", []),
            fee_type=payload.get("fee_type", "none"),
            fee_amount=_optional_decimal(payload, "fee_amount"),
            fee_charged_to=payload.get("fee_charged_to", "customer"),
            instructions=payload.get("instructions"),
            config=payload.get("config", {}),
        )

        if method.is_default:
            self._clear_other_defaults()

        return self._repository.save(method)

    # ── private helpers ──────────────────────────────────────────────────

    def _require(self, payload: Mapping[str, Any], field: str) -> None:
        if not payload.get(field):
            raise PaymentMethodValidationError(f"{field.capitalize()} is required")

    def _clear_other_defaults(self) -> None:
        self._session.query(PaymentMethod).filter(
            PaymentMethod.is_default.is_(True)
        ).update({"is_default": False})
