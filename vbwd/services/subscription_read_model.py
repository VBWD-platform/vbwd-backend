"""Generic subscription read port — core stays subscription-agnostic.

Admin invoice/user views need a few subscription-derived fields. Core no
longer reaches into subscription repositories for them; it defines this
narrow read port and the subscription plugin supplies the implementation.
When no provider is registered (subscription plugin disabled) the null
default yields empty enrichment — no error (locked decision: empty/None).
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from uuid import UUID


class ISubscriptionReadModel(ABC):
    """Narrow read-only port (ISP) — only what core admin surfaces need."""

    @abstractmethod
    def enrich_invoice(self, invoice: Any) -> Dict[str, Any]:
        """Extra invoice-detail keys (plan_* / subscription_*). {} if none."""

    @abstractmethod
    def count_user_subscriptions(self, user_id: UUID) -> int:
        """Number of subscriptions for a user (delete dependency check)."""

    @abstractmethod
    def user_addon_subscriptions(self, user_id: UUID) -> List[Dict[str, Any]]:
        """Serialised add-on subscriptions for the admin user view."""

    @abstractmethod
    def active_subscription_count(self) -> int:
        """Total active subscriptions (admin analytics metric). 0 if none."""


class _NullSubscriptionReadModel(ISubscriptionReadModel):
    """Used when the subscription plugin is disabled — empty enrichment."""

    def enrich_invoice(self, invoice: Any) -> Dict[str, Any]:
        return {}

    def count_user_subscriptions(self, user_id: UUID) -> int:
        return 0

    def user_addon_subscriptions(self, user_id: UUID) -> List[Dict[str, Any]]:
        return []

    def active_subscription_count(self) -> int:
        return 0


_read_model: Optional[ISubscriptionReadModel] = None


def register_subscription_read_model(read_model: ISubscriptionReadModel) -> None:
    """Called by the subscription plugin on enable."""
    global _read_model
    _read_model = read_model


def clear_subscription_read_model() -> None:
    """Reset to the null default (plugin disable / test teardown)."""
    global _read_model
    _read_model = None


def resolve_subscription_read_model() -> ISubscriptionReadModel:
    """The registered read model, or the empty null default."""
    return _read_model if _read_model is not None else _NullSubscriptionReadModel()
