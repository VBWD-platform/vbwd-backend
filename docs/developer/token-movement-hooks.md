# Token-movement hooks

An **atomic, in-transaction seam** for observing (and vetoing) every change to a
user's token balance. Added in S138.0 so an external bookkeeper — for example a
double-entry ledger keeping a mirror "cash" account — can stay **exactly** in
sync with the core token balance, with no drift.

- Module: `vbwd/services/token_balance_hooks.py`
- Fired by: `vbwd/services/token_service.py`
- Style: a module-level registry, like `user_provisioning_guard_registry`
  (core owns the mechanism; the domain lives in whatever registers a hook).

## Why a hook and not an event

The EventBus (`vbwd/events/bus.py`) is **best-effort**: a subscriber that raises
is logged and swallowed, and subscribers run in their own transaction. That is
correct for notifications and analytics, but fatal for bookkeeping — a failed
mirror post would leave the ledger silently out of step with the balance.

A token-movement hook instead runs **inside the movement's own transaction**,
after the balance and its `TokenTransaction` are flushed but **before commit**.
So:

- a hook sees the movement on the **live session** and can post a counter-entry
  in the *same* transaction; and
- a hook that **raises rolls the whole movement back** — the balance change and
  its `TokenTransaction` never commit.

With no hook registered the token path is unchanged.

> Also emitted, separately: a best-effort `token.moved` EventBus event **after
> commit**, for non-critical consumers (notifications, analytics). Use the hook
> for anything that must not drift; the event for anything that may.

## The contract

```python
@dataclass(frozen=True)
class TokenMovement:
    user_id: UUID
    delta: int                       # signed: + on credit, - on debit (never absolute)
    balance_after: int
    transaction_type: TokenTransactionType
    reference_id: Optional[UUID] = None
    description: Optional[str] = None

class ITokenMovementHook(ABC):
    def on_token_moved(self, movement: TokenMovement, session) -> None: ...
```

`register_token_movement_hook(hook)` / `clear_token_movement_hooks()` /
`token_movement_hooks()` / `run_token_movement_hooks(movement, session)`.

## Registering a hook (from a plugin)

Register in `on_enable`, clear in `on_disable`:

```python
from vbwd.services.token_balance_hooks import (
    ITokenMovementHook, TokenMovement,
    register_token_movement_hook, clear_token_movement_hooks,
)

class LedgerMirror(ITokenMovementHook):
    def on_token_moved(self, movement: TokenMovement, session) -> None:
        # runs in the movement's transaction; raising aborts the movement
        post_mirror_leg(session, user_id=movement.user_id, delta=movement.delta,
                        reason=movement.transaction_type)

class MyPlugin(BasePlugin):
    def on_enable(self):  register_token_movement_hook(LedgerMirror())
    def on_disable(self): clear_token_movement_hooks()
```

The `transaction_type` (`TokenTransactionType`) tells the hook **why** the
tokens moved — `PURCHASE`, `USAGE`, `BONUS`, `WITHDRAW`, `REFUND`,
`ADJUSTMENT`, `SUBSCRIPTION`, `REFERRAL_COMMISSION` — so a bookkeeper can route
each to the right counter-account. A hook that originates a movement itself
(e.g. an exchange service that *calls* `TokenService`) must guard against
double-posting the leg it already booked.

## The guarantee that makes this safe

`TokenService` is the **only** site in the codebase that mutates
`UserTokenBalance.balance` or constructs a `TokenTransaction`. This is enforced
by an AST oracle (`tests/unit/test_token_balance_write_oracle.py`) that fails CI
if any other module writes a token balance directly. So "every movement fires a
hook" holds **by construction** — including for code not yet written. If you
need to move tokens, call `TokenService.credit_tokens` / `debit_tokens`; never
write the balance directly.

Related invariant, also new in S138.0: a balance change and its
`TokenTransaction` now commit **together** (one unit of work), so
`balance == Σ(TokenTransaction.amount)` for every user. `credit_tokens` /
`debit_tokens` take `commit=False` to compose inside a caller's larger
transaction, and reject non-integral amounts (`TypeError`).
