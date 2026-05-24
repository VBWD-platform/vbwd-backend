"""Generic entitlement port — core knows nothing about subscriptions.

Feature gating used to live in core `FeatureGuard`, which depended on the
subscription repository. Core now only defines this narrow port; the
subscription plugin supplies the concrete provider. When no provider is
registered (subscription plugin disabled), the default honours decision D3:
**allow** unless the core config flag `ENTITLEMENT_DEFAULT_ALLOW` is False.
"""
from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple
from uuid import UUID

from flask import current_app


class IEntitlementProvider(ABC):
    """Narrow port (ISP) — only what the permission decorators need."""

    @abstractmethod
    def is_feature_allowed(self, user_id: UUID, feature_name: str) -> bool:
        """Whether the user may access the named feature."""

    @abstractmethod
    def check_usage_limit(
        self, user_id: UUID, feature_name: str, amount: int = 1
    ) -> Tuple[bool, Optional[int]]:
        """(within_limit, remaining). remaining is None for unlimited."""

    @abstractmethod
    def get_feature_value(
        self, user_id: UUID, feature_name: str, default: Any = None
    ) -> Any:
        """Value of a plan feature for the user's active plan, or ``default``.

        Lets feature plugins (e.g. taro) read plan-driven limits without
        importing the subscription model. ``default`` is returned when no
        provider / active plan supplies the feature (D3-friendly)."""

    @abstractmethod
    def current_plan_name(self, user_id: UUID) -> Optional[str]:
        """Display name of the user's active plan, or None (no plan/plugin)."""


class _DefaultEntitlementProvider(IEntitlementProvider):
    """Used when no provider is registered (e.g. subscription plugin off).

    D3: default to allow so booking/shop installs — which have no plan
    concept — are not gated by an absent one. A core config flag can flip
    the default to deny.
    """

    def _default_allows(self) -> bool:
        try:
            return bool(current_app.config.get("ENTITLEMENT_DEFAULT_ALLOW", True))
        except RuntimeError:
            # No app context — be permissive (D3 default).
            return True

    def is_feature_allowed(self, user_id: UUID, feature_name: str) -> bool:
        return self._default_allows()

    def check_usage_limit(
        self, user_id: UUID, feature_name: str, amount: int = 1
    ) -> Tuple[bool, Optional[int]]:
        return (self._default_allows(), None if self._default_allows() else 0)

    def get_feature_value(
        self, user_id: UUID, feature_name: str, default: Any = None
    ) -> Any:
        # No plan concept without the subscription plugin — the caller's
        # default (e.g. taro's free-tier limit) applies.
        return default

    def current_plan_name(self, user_id: UUID) -> Optional[str]:
        return None


_provider: Optional[IEntitlementProvider] = None


def register_entitlement_provider(provider: IEntitlementProvider) -> None:
    """Called by the subscription plugin on enable."""
    global _provider
    _provider = provider


def clear_entitlement_provider() -> None:
    """Reset to the default (plugin disable / test teardown)."""
    global _provider
    _provider = None


def resolve_entitlement_provider() -> IEntitlementProvider:
    """The registered provider, or the D3 default when none is registered."""
    return _provider if _provider is not None else _DefaultEntitlementProvider()
