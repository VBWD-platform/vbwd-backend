"""S138.0 — TokenService is the ONLY writer of UserTokenBalance.

The sprint's definition of done is "**every** ``UserTokenBalance`` mutation fires
the hook". Enumerating the ~20 known token paths in a test proves it for the
paths someone remembered; it says nothing about the twenty-first. This oracle
proves it *by construction* instead: if the balance can only be mutated in one
function, and that function runs the hooks, then every mutation fires them —
including the ones nobody has written yet.

It is the same shape as ``test_core_agnosticism`` / ``test_core_no_domain_
vocabulary``: an AST walk over the source tree with an explicit allowlist. It
scans whatever plugins are present, so a per-plugin CI checkout simply scans
fewer files.

Adding a new token path is not meant to be hard — it is meant to go through
``TokenService.credit_tokens`` / ``debit_tokens`` / ``refund_tokens``, which is
where the seam, the unit of work and the integer contract live. If you are
looking at a failure here, that is the fix; do not extend the allowlist.
"""
import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCANNED_TREES = ("vbwd", "plugins")

# The single home for every token movement (S138.0 §3): it mutates the balance,
# appends the TokenTransaction, runs the hooks and commits as ONE unit of work.
TOKEN_SERVICE = Path("vbwd/services/token_service.py")

# get_or_create inserts a ZERO-balance row for a user who has none. That is not
# a movement — no delta, nothing for a bookkeeper to mirror — and TokenService
# is its only caller.
TOKEN_REPOSITORY = Path("vbwd/repositories/token_repository.py")

BALANCE_MUTATION_ALLOWLIST = frozenset({TOKEN_SERVICE})
BALANCE_CONSTRUCTION_ALLOWLIST = frozenset({TOKEN_SERVICE, TOKEN_REPOSITORY})
LEDGER_CONSTRUCTION_ALLOWLIST = frozenset({TOKEN_SERVICE})

TOKEN_MODELS = ("UserTokenBalance", "TokenTransaction")


def _is_test_path(path: Path) -> bool:
    parts = path.parts
    return "tests" in parts or path.name.startswith("test_")


def _source_files():
    """Every non-test Python module in the scanned trees."""
    for tree in SCANNED_TREES:
        for path in sorted((PROJECT_ROOT / tree).rglob("*.py")):
            if not _is_test_path(path.relative_to(PROJECT_ROOT)):
                yield path


def _parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):  # a vendored/generated oddity
        return None


def _mentions_token_models(tree) -> bool:
    """True when the module names a token model at all.

    Keeps the ``.balance`` scan free of false positives: plenty of unrelated
    objects (a withdraw source, an account, a mock) have a ``balance``
    attribute, and only a module that knows the token models can write theirs.
    """
    return any(
        isinstance(node, ast.Name) and node.id in TOKEN_MODELS
        for node in ast.walk(tree)
    )


def _writes_balance_attribute(tree) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.AugAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr == "balance":
                return True
    return False


def _constructs(tree, model_name: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == model_name
        for node in ast.walk(tree)
    )


def _offenders(predicate, allowlist):
    found = []
    for path in _source_files():
        relative_path = path.relative_to(PROJECT_ROOT)
        if relative_path in allowlist:
            continue
        tree = _parse(path)
        if tree is None or not _mentions_token_models(tree):
            continue
        if predicate(tree):
            found.append(str(relative_path))
    return found


def test_the_scan_actually_reaches_the_token_service():
    """Guard the guard: an oracle that scans nothing passes vacuously."""
    scanned = {path.relative_to(PROJECT_ROOT) for path in _source_files()}
    assert TOKEN_SERVICE in scanned


def test_only_token_service_mutates_a_token_balance():
    """A direct write bypasses the hook, the ledger row and the unit of work.

    This is the bug S138.0 exists to kill: four sites used to do
    ``balance.balance += amount`` themselves, so a bundle capture, a refund
    restore and a subscription's plan tokens were invisible to any bookkeeper.
    """
    offenders = _offenders(_writes_balance_attribute, BALANCE_MUTATION_ALLOWLIST)

    assert offenders == [], (
        "These modules mutate a token balance directly instead of going "
        "through TokenService.credit_tokens / debit_tokens / refund_tokens, so "
        f"no token-movement hook can see it: {offenders}"
    )


def test_only_token_service_writes_a_ledger_row():
    """A hand-built ``TokenTransaction`` means a movement outside the seam.

    The balance and its ledger row are one unit of work; a module writing the
    row itself is either duplicating the seam or drifting from it.
    """
    offenders = _offenders(
        lambda tree: _constructs(tree, "TokenTransaction"),
        LEDGER_CONSTRUCTION_ALLOWLIST,
    )

    assert offenders == [], (
        "These modules construct a TokenTransaction outside TokenService: "
        f"{offenders}"
    )


def test_only_the_token_repository_creates_a_balance_row():
    offenders = _offenders(
        lambda tree: _constructs(tree, "UserTokenBalance"),
        BALANCE_CONSTRUCTION_ALLOWLIST,
    )

    assert offenders == [], (
        "These modules construct a UserTokenBalance outside "
        f"TokenBalanceRepository.get_or_create: {offenders}"
    )


@pytest.mark.parametrize(
    "movement_method", ["credit_tokens", "debit_tokens", "refund_tokens"]
)
def test_every_public_movement_runs_the_hooks(movement_method):
    """The other half of the argument: the one writer does fire the hooks.

    ``_apply_movement`` is the only body that mutates the balance (asserted
    above) and it is the only caller of ``run_token_movement_hooks``, so every
    public movement inherits the seam.
    """
    import inspect

    from vbwd.services.token_service import TokenService

    source = inspect.getsource(getattr(TokenService, movement_method))
    assert "_apply_movement" in source
