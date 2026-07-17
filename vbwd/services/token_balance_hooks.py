"""Registry of token-movement hooks (observe-and-veto seam for token balance changes).

Core's :class:`~vbwd.services.token_service.TokenService` runs every registered
hook INSIDE its own transaction, AFTER the balance and its ``TokenTransaction``
are flushed but BEFORE the commit. So a hook sees the movement on the live
session and — crucially — a hook that raises makes ``TokenService`` roll the
whole movement back. Core owns the mechanism: the :class:`TokenMovement` it
hands each hook. The domain lives entirely in whatever registers a hook (an
external ledger keeping a mirror account, an audit trail, a quota counter) —
core names none of them (mirrors ``user_provisioning_guard_registry`` and
``deletion_dependency_registry``: core owns the mechanism, the domain arrives
from plugins).

Unlike the best-effort EventBus (which logs-and-swallows a subscriber error),
these hooks **propagate**: they run in the token movement's own transaction and
their failure must abort it, or a mirror could silently drift from the core
balance. With nothing registered the token path is unchanged — no behaviour
change, no cost.

A plugin registers its hook from ``on_enable`` (and clears it on disable)::

    from vbwd.services.token_balance_hooks import (
        ITokenMovementHook,
        register_token_movement_hook,
    )

    class LedgerMirror(ITokenMovementHook):
        def on_token_moved(self, movement, session):
            _post_counter_leg(session, movement)   # same transaction; may raise

    register_token_movement_hook(LedgerMirror())
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional
from uuid import UUID

from vbwd.models.enums import TokenTransactionType


@dataclass(frozen=True)
class TokenMovement:
    """A single change to a user's token balance, as seen by a hook.

    ``delta`` is signed: positive on a credit, negative on a debit — never an
    absolute balance. ``balance_after`` is the resulting balance. ``session`` is
    passed separately to :meth:`ITokenMovementHook.on_token_moved` so a hook can
    perform a side effect in the SAME transaction that is moving the tokens.
    """

    user_id: UUID
    delta: int
    balance_after: int
    transaction_type: TokenTransactionType
    reference_id: Optional[UUID] = None
    description: Optional[str] = None


class ITokenMovementHook(ABC):
    """A hook run on every token movement, inside the movement's transaction."""

    @abstractmethod
    def on_token_moved(self, movement: TokenMovement, session: Any) -> None:
        """React to ``movement`` on the live ``session``.

        Runs before the movement commits. Raising aborts the whole movement
        (the balance change AND its ``TokenTransaction`` roll back together).
        """


_hooks: List[ITokenMovementHook] = []


def register_token_movement_hook(hook: ITokenMovementHook) -> None:
    """Register a hook (plugin enable). Hooks run in registration order."""
    _hooks.append(hook)


def clear_token_movement_hooks() -> None:
    """Reset all hooks (plugin disable / test teardown)."""
    _hooks.clear()


def token_movement_hooks() -> List[ITokenMovementHook]:
    """The registered hooks, in registration order (read-only copy)."""
    return list(_hooks)


def run_token_movement_hooks(movement: TokenMovement, session: Any) -> None:
    """Run each hook in order; an exception propagates to abort the movement."""
    for hook in _hooks:
        hook.on_token_moved(movement, session)
