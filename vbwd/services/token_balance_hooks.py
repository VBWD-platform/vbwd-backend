"""Registry of token-movement hooks (plugin-contributed observation seam).

Core's ``TokenService`` runs every registered hook INSIDE its own transaction,
BEFORE it commits, handing over the live session. So a plugin that mirrors token
movements (an external ledger, an audit trail, a quota counter) posts its own
rows on the same unit of work: the token write and the plugin's posting commit
or roll back **together**. A hook raising propagates — the movement is undone.

This is deliberately NOT the ``EventBus``: the bus swallows subscriber
exceptions and commits separately, which is fine for best-effort consumers
(notifications, analytics) but would let a failed mirror leave the two sides
silently diverged. Critical bookkeeping needs the transaction, so it needs a
hook.

Core owns the mechanism only: ``TokenMovement`` names no plugin and no domain —
it is the shape of "someone moved tokens", nothing more (mirrors
``user_provisioning_guard_registry`` and ``line_item_registry``: core defines
the port, the domain arrives from plugins).

With nothing registered the token paths are unchanged — no behaviour change, so
the disabled-plugin path degrades gracefully.

A plugin registers its hook from ``on_enable`` (and clears it on disable)::

    from vbwd.services.token_balance_hooks import (
        ITokenMovementHook,
        register_token_movement_hook,
    )

    class LedgerMirror(ITokenMovementHook):
        def on_token_moved(self, movement, session):
            session.add(_posting_for(movement))

    register_token_movement_hook(LedgerMirror())
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional
from uuid import UUID

from vbwd.models.enums import TokenTransactionType


@dataclass(frozen=True)
class TokenMovement:
    """One change to a user's token balance, as core saw it.

    ``delta`` is SIGNED — positive credits, negative debits — never the absolute
    amount, so a subscriber can sum movements without re-deriving direction from
    ``transaction_type``. ``balance_after`` is the balance once the movement is
    applied, letting a mirror assert it agrees with core rather than guess.
    ``reference_id`` is whatever the caller correlated the movement with (an
    invoice, a purchase, a transfer) and doubles as a subscriber's idempotency
    key.
    """

    user_id: UUID
    delta: int
    balance_after: int
    transaction_type: TokenTransactionType
    reference_id: Optional[UUID] = None
    description: Optional[str] = None


class ITokenMovementHook(ABC):
    """Interface for plugin token-movement hooks."""

    @abstractmethod
    def on_token_moved(self, movement: TokenMovement, session: Any) -> None:
        """React to a token movement on the caller's OPEN transaction.

        ``session`` is core's live session: writes made here commit with the
        token movement. Raising vetoes the movement — core rolls the whole unit
        of work back and re-raises, so a hook must raise rather than swallow a
        failure it cannot absorb.
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
    """Run each hook in order; the first to raise aborts the movement.

    Exceptions propagate on purpose (unlike the ``EventBus``): the caller owns
    the transaction and rolls it back, so a hook's failure can never leave the
    token balance moved.
    """
    for hook in _hooks:
        hook.on_token_moved(movement, session)
