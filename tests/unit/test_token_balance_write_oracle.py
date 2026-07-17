"""S138.0 oracle — ``TokenService`` is the ONLY writer of the token balance.

The S138 ledger can only mirror the core token balance exactly if EVERY change
to a user's tokens flows through one seam. This oracle enforces that structural
invariant the same way ``test_core_agnosticism`` enforces the plugin boundary:
it AST-walks core (``vbwd/``) AND every plugin (``plugins/``) and asserts that
``vbwd/services/token_service.py`` is the single site that either

  (a) mutates a token balance — assigns to an attribute named ``balance``
      (``x.balance = ...``, ``x.balance += ...``, ``x.balance -= ...``), or
  (b) constructs a ``TokenTransaction(...)`` ledger row.

Every other token movement must go through ``TokenService.credit_tokens`` /
``debit_tokens`` / ``refund_tokens``, so the movement fires the token-movement
hooks and appends its ``TokenTransaction`` atomically. A direct
``balance.balance += n`` or a hand-built ``TokenTransaction(...)`` anywhere else
bypasses the seam — the exact class of hole (core bundle capture/refund, the
subscription plan-token write, the admin absolute-set) S138.0 exists to close.

**Code-only:** tests, fixtures (``conftest.py``) and migrations are excluded —
they legitimately fabricate balances and ledger rows to set up state. The
``class TokenTransaction(BaseModel)`` definition and the ``__repr__`` string are
not constructor CALLS, so they are never flagged.
"""
import ast
import os
import tempfile

# The one legitimate writer, relative to the backend root. Every other match is
# a bypass of the token seam.
ALLOWED_WRITE_SITE = os.path.join("vbwd", "services", "token_service.py")

# Roots scanned for bypasses: core and every plugin.
SCANNED_ROOTS = ("vbwd", "plugins")

# The attribute whose assignment mutates a token balance.
BALANCE_ATTRIBUTE = "balance"

# The ledger-row model whose construction must live in the seam alone.
LEDGER_MODEL = "TokenTransaction"


def _backend_root() -> str:
    """Absolute path to ``vbwd-backend/`` (parent of this test's grandparent)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def _is_excluded(path: str) -> bool:
    """True for tests / fixtures / migrations — not production token code.

    Those trees legitimately fabricate balances and ledger rows to arrange test
    state, so scanning them would report noise rather than real bypasses.
    """
    normalized = path.replace(os.sep, "/")
    if "/__pycache__/" in normalized:
        return True
    if "/tests/" in normalized or "/test/" in normalized:
        return True
    if "/migrations/" in normalized:
        return True
    filename = os.path.basename(normalized)
    return filename.startswith("test_") or filename == "conftest.py"


def _iter_scanned_python_files():
    """Yield every production ``.py`` file under the scanned roots."""
    backend_root = _backend_root()
    for scanned_root in SCANNED_ROOTS:
        absolute_root = os.path.join(backend_root, scanned_root)
        if not os.path.isdir(absolute_root):
            continue
        for dirpath, _dirs, files in os.walk(absolute_root):
            if "__pycache__" in dirpath:
                continue
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                if _is_excluded(path):
                    continue
                yield path


def _iter_attribute_targets(target: ast.expr):
    """Yield every ``ast.Attribute`` reached through nested tuple/list targets.

    Catches ``a.balance = x`` and ``a.balance, other = x`` alike.
    """
    if isinstance(target, ast.Attribute):
        yield target
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _iter_attribute_targets(element)


def _balance_writes_in(path: str) -> list[tuple[int, str]]:
    """``(lineno, snippet)`` for every write to an attribute named ``balance``."""
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    writes: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        else:
            continue
        for target in targets:
            for attribute in _iter_attribute_targets(target):
                if attribute.attr == BALANCE_ATTRIBUTE:
                    writes.append((node.lineno, ast.unparse(node)))
    return writes


def _token_transaction_constructions_in(path: str) -> list[tuple[int, str]]:
    """``(lineno, snippet)`` for every ``TokenTransaction(...)`` call."""
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    constructions: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        called_name = None
        if isinstance(callee, ast.Name):
            called_name = callee.id
        elif isinstance(callee, ast.Attribute):
            called_name = callee.attr
        if called_name == LEDGER_MODEL:
            constructions.append((node.lineno, ast.unparse(node.func)))
    return constructions


def _bypasses(collector) -> list[str]:
    """``relpath:lineno — snippet`` for every hit outside the allowed site."""
    backend_root = _backend_root()
    findings: list[str] = []
    for path in _iter_scanned_python_files():
        relpath = os.path.relpath(path, backend_root)
        if relpath == ALLOWED_WRITE_SITE:
            continue
        for lineno, snippet in collector(path):
            findings.append(f"{relpath}:{lineno} — {snippet}")
    return findings


def test_only_token_service_mutates_a_token_balance():
    """The load-bearing gate: no ``x.balance = / += / -=`` outside the seam."""
    findings = _bypasses(_balance_writes_in)
    assert not findings, (
        "Only vbwd/services/token_service.py may mutate a token balance — every "
        "other write bypasses the token-movement hook seam (S138.0). Found "
        f"{len(findings)} bypass(es):\n  - " + "\n  - ".join(findings)
    )


def test_only_token_service_constructs_a_token_transaction():
    """No hand-built ``TokenTransaction(...)`` outside the seam."""
    findings = _bypasses(_token_transaction_constructions_in)
    assert not findings, (
        "Only vbwd/services/token_service.py may construct a TokenTransaction — "
        "a ledger row built elsewhere is a movement with no hook (S138.0). Found "
        f"{len(findings)} bypass(es):\n  - " + "\n  - ".join(findings)
    )


def test_the_allowed_site_actually_writes_the_balance_and_transaction():
    """Guard the allowlist against rot: the seam must still be the writer.

    If the balance mutation or the ``TokenTransaction`` construction ever leaves
    ``token_service.py``, the two gates above would pass vacuously. This proves
    the allowlisted file really is where both happen.
    """
    seam = os.path.join(_backend_root(), ALLOWED_WRITE_SITE)
    assert _balance_writes_in(seam), "the seam no longer mutates .balance"
    assert _token_transaction_constructions_in(
        seam
    ), "the seam no longer constructs TokenTransaction"


def test_oracle_scans_both_core_and_plugins():
    """The scan must cover core AND plugins — a plugin bypass must be reachable."""
    scanned = {
        os.path.relpath(path, _backend_root()).split(os.sep, 1)[0]
        for path in _iter_scanned_python_files()
    }
    assert "vbwd" in scanned
    assert "plugins" in scanned


def _write_temp_module(source: str) -> str:
    """Write ``source`` to a throwaway ``.py`` file and return its path."""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    )
    handle.write(source)
    handle.close()
    return handle.name


def test_oracle_detects_a_planted_balance_mutation():
    """Self-test: a stray ``obj.balance += n`` IS caught (the oracle bites)."""
    planted = _write_temp_module(
        "def leak(obj):\n"
        "    obj.balance += 999\n"
        "    obj.balance = 0\n"
        "    obj.balance -= 1\n"
    )
    try:
        writes = _balance_writes_in(planted)
    finally:
        os.unlink(planted)
    assert len(writes) == 3


def test_oracle_detects_a_planted_token_transaction_construction():
    """Self-test: a stray ``TokenTransaction(...)`` IS caught."""
    planted = _write_temp_module(
        "def leak(user_id):\n"
        "    return TokenTransaction(user_id=user_id, amount=5)\n"
    )
    try:
        constructions = _token_transaction_constructions_in(planted)
    finally:
        os.unlink(planted)
    assert len(constructions) == 1


def test_oracle_ignores_balance_reads_and_the_class_definition():
    """Self-test: reads, the model definition and its repr string are NOT hits."""
    benign = _write_temp_module(
        "class TokenTransaction(BaseModel):\n"
        "    def __repr__(self):\n"
        "        return '<TokenTransaction(amount=1)>'\n"
        "\n"
        "def read(obj):\n"
        "    current = obj.balance\n"
        "    return current\n"
    )
    try:
        assert _balance_writes_in(benign) == []
        assert _token_transaction_constructions_in(benign) == []
    finally:
        os.unlink(benign)
