"""Registry of user-provisioning guards (plugin-contributed veto seam).

Core's ``UserService.admin_create`` runs every registered guard BEFORE it
persists a new user, so a plugin can veto provisioning — for example enforcing a
seat count or a token balance — without core naming any policy. Core owns the
mechanism: the ``UserProvisioningRequest`` it hands to each guard and the
``UserProvisioningBlocked`` veto a guard raises. The domain policy lives
entirely in the plugin that registers a guard (mirrors
``deletion_dependency_registry`` and ``licensed_feature_registry``: core owns
the mechanism, the domain arrives from plugins).

With nothing registered the provisioning path is unchanged — no behaviour
change, the disabled-plugin path degrades gracefully.

A plugin registers its guard from ``on_enable`` (and clears it on disable)::

    from vbwd.registries.user_provisioning_guard_registry import (
        UserProvisioningBlocked,
        register_user_provisioning_guard,
    )

    def _enforce_seats(request):
        if _no_seats_left(request):
            raise UserProvisioningBlocked(
                "Seat limit reached",
                code="SEAT_LIMIT_REACHED",
                status=402,
                action_label="Buy seats",
                action_url="/billing/seats",
            )

    register_user_provisioning_guard(_enforce_seats)
"""
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from vbwd.models.enums import UserRole

_DEFAULT_BLOCKED_STATUS = 403


@dataclass(frozen=True)
class UserProvisioningRequest:
    """What a guard needs to decide whether provisioning may proceed.

    ``action`` is a coarse verb (e.g. ``"create"``). ``acting_user_id`` is the
    admin performing the action (``g.user_id``), or ``None`` for a system path.
    ``session`` is the active transaction, so a guard may perform a side effect
    (e.g. debit a balance) — that is the plugin's business; core just runs the
    guard.
    """

    action: str
    email: str
    role: UserRole
    acting_user_id: Optional[str]
    session: Any


class UserProvisioningBlocked(Exception):
    """Structured veto a guard raises to stop provisioning.

    Core defines the envelope and names NO policy: ``code`` is a machine string
    the guard chooses (the route echoes it verbatim), ``status`` lets a guard
    pick 402 vs 403, and ``action_label`` / ``action_url`` let the frontend
    render a call-to-action hyperlink.
    """

    def __init__(
        self,
        message: str,
        code: str,
        status: int = _DEFAULT_BLOCKED_STATUS,
        action_label: Optional[str] = None,
        action_url: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.action_label = action_label
        self.action_url = action_url


# A guard runs for side effects and raises ``UserProvisioningBlocked`` to veto.
UserProvisioningGuard = Callable[[UserProvisioningRequest], None]

_guards: List[UserProvisioningGuard] = []


def register_user_provisioning_guard(guard: UserProvisioningGuard) -> None:
    """Register a guard (plugin enable). Guards run in registration order."""
    _guards.append(guard)


def clear_user_provisioning_guards() -> None:
    """Reset all guards (plugin disable / test teardown)."""
    _guards.clear()


def user_provisioning_guards() -> List[UserProvisioningGuard]:
    """The registered guards, in registration order (read-only copy)."""
    return list(_guards)


def run_user_provisioning_guards(request: UserProvisioningRequest) -> None:
    """Run each guard in order; the first to raise vetoes (later guards skip)."""
    for guard in _guards:
        guard(request)
