"""S50 oracle — core (`vbwd/`) must name NO plugin domain vocabulary.

Companion to ``test_core_agnosticism.py`` (which bans ``from plugins.*``).
This one bans the *vocabulary* of specific plugin domains from core **code** —
identifiers, imports, and string literals — so core stays **event-aware, not
domain-aware** (S50 governing principle).

**Code-only (AST):** the oracle parses each core file and inspects only
*identifiers* (Name / attribute / arg / function+class names / import module +
alias names) and *non-docstring string-literal Constants*. Comments and
docstrings are **never** scanned — they are domain-NEUTRAL meta-text (e.g.
``entitlement.py``'s "core knows nothing about subscriptions" docstring, or
``transaction.py``'s ``Usage:`` examples) and are not leaks. Comments do not
appear in the AST at all; module/class/function docstrings (the first
``ast.Expr`` holding a ``str`` ``Constant``) are explicitly skipped.

Banned terms (whole-word, case-insensitive): ``subscription(s)``, ``tarif``,
``tarif_plan``, ``plan_id`` / ``plan_name`` (as core symbols), ``seo``,
``sitemap``. (``catalog`` is intentionally NOT banned — it is a generic
English word, see ``BANNED_TERMS`` note.)

**Mode:** ``ENFORCING`` gates failure. Now **True** (S50.5 lock): the oracle
fails on any non-allowlisted hit. ``ALLOWLIST`` carries the documented,
justified structural residuals.

Allowlist entries are ``(relpath, term)`` pairs for genuine structural uses
that survive the cleanup; each MUST carry a justifying comment.
"""
import ast
import os
import re

# S50.5: enforcing — fail on any non-allowlisted banned-term hit in core CODE.
ENFORCING = True

# Whole-word, case-insensitive banned domain terms (ordered longest/most
# specific first so the reported term is the precise one).
#
# NOTE: ``catalog`` is deliberately NOT here. It is a generic English word that
# appears in legitimate core identifiers (``permission_catalog``,
# ``collect_permission_catalog``, ``catalog_item_id``, ``routes_catalog``,
# country / payment-method "catalog"). The real domain leak
# (``catalog_read_model``, the plan-catalog port) was deleted in S50.1 and is
# independently guarded by ``test_core_agnosticism`` (bans ``from plugins.*``).
BANNED_TERMS = (
    "subscriptions",
    "subscription",
    "tarif_plan",
    "tarif",
    "plan_id",
    "plan_name",
    "sitemap",
    "seo",
)

# (relpath_under_vbwd's parent, term) pairs that are genuine STRUCTURAL
# residuals and may remain. Each carries a justification grouped by bucket.
# Kept MINIMAL: only entries that match a real CODE hit are listed — the
# AST/whole-word scan already drops prose and compound identifiers (e.g.
# ``subscription_id``, ``get_subscription_invoices``, ``find_by_subscription``
# never match the standalone word), so most spec-anticipated files need no
# entry.
ALLOWLIST: set[tuple[str, str]] = {
    # --- (a) D4-accepted invoice residuals -------------------------------
    # Sprint 11 decision: invoice ↔ subscription is linked via a SUBSCRIPTION
    # line item (item_id == subscription.id), NOT a FK. The only standalone-
    # word hits are the line-item-result dict keys and the repo method's
    # enum value — the deliberate residual of the subscription-extraction
    # sprint. (invoice_service/invoice/admin-invoices etc. only use compound
    # identifiers, which the whole-word scan already ignores.)
    (
        "vbwd/repositories/invoice_repository.py",
        "subscription",
    ),  # LineItemType.SUBSCRIPTION
    # line-item-result dict keys: items_*["subscription"] = data["subscription_id"]
    ("vbwd/handlers/payment_handler.py", "subscription"),
    ("vbwd/services/restore_service.py", "subscription"),
    ("vbwd/services/refund_service.py", "subscription"),
    # --- (b) Core line-item / status enums -------------------------------
    # The generic discriminator core routes on (LineItemType.SUBSCRIPTION,
    # TokenTransactionType.SUBSCRIPTION) and the status enums core stores;
    # core never reads a plan/tarif field.
    ("vbwd/models/enums.py", "subscription"),
    # --- (c) Core webhook event-type enums -------------------------------
    # SUBSCRIPTION_* members / "subscription.*" event-name strings. FUTURE:
    # like the SSE whitelist (S50.6), these could become an extensible
    # registry; deferred — allowlisted for now.
    ("vbwd/webhooks/enums.py", "subscription"),
    ("vbwd/webhooks/handlers/mock.py", "subscription"),
    # --- (d) Demo / test seeders (DEFERRED follow-up) --------------------
    # Core demo seeds delegate plan/addon to the subscription plugin's
    # demo_seed but still name tables/keys (raw-SQL "tarif_plan" /
    # "subscription" table strings; the reset-demo CLI confirm prompt). Own
    # follow-up sprint — allowlisted now.
    ("vbwd/cli/_demo_seeder.py", "tarif_plan"),
    ("vbwd/cli/_demo_seeder.py", "subscription"),
    ("vbwd/cli/reset_demo.py", "subscriptions"),  # CLI confirm-prompt text
    # --- (e) Not in the spec's enumerated buckets — decided in S50.5 ------
    # Two structural hits surfaced that the spec's buckets did not name. Both
    # are domain-NEUTRAL by category (provider-protocol literal / fallback
    # content prose), NOT a core-reads-a-plugin-field leak. Reported to the
    # user with this reasoning; allowlisted pending veto.
    #
    # determine_session_mode() returns the Stripe Checkout Session `mode`
    # value ("subscription" | "payment") — provider-protocol vocabulary that
    # core computes generically via line_item_registry.is_recurring_line_item
    # and the payment plugins pass straight to the SDK. Like bucket (c), this
    # could later move behind the line-item registry; deferred.
    ("vbwd/plugins/payment_route_helpers.py", "subscription"),
    # routes/settings.py GET /terms returns a DEFAULT Terms & Conditions text
    # blob whose boilerplate names "Subscription Services". This is fallback
    # content prose (editable user content), not a domain seam.
    ("vbwd/routes/settings.py", "subscriptions"),
    # --- (f) FilesystemManager namespace name (S58.0) --------------------
    # The unified FilesystemManager (agnostic core infrastructure) registers a
    # "seo" *namespace* in its managed-tree registry — a file-routing label
    # under ${VBWD_VAR_DIR}/seo/, NOT core reading an SEO domain field. The
    # manager knows files, not domains; the SEO plugin (S58.2) writes through
    # this namespace via the DI container. Pure filesystem vocabulary.
    ("vbwd/services/filesystem/_common.py", "seo"),
    # --- (g) Route-exposure allowlist (S90 G1) ---------------------------
    # RESOLVED: ``route_audit.py`` no longer names any plugin route string. The
    # public-route allowlist was inverted into a plugin-declared seam
    # (``BasePlugin.declare_public_routes()``); core keeps only genuinely-core
    # public paths (auth/config/settings/token-bundles), so the former tarif /
    # subscription / plan_id / sitemap exemptions are gone. The guard test
    # ``test_core_allowlists_contain_no_plugin_route`` proves core stays clean.
}

_TERM_RE = {
    term: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", re.I)
    for term in BANNED_TERMS
}


def _matched_term(text: str) -> str | None:
    """First banned term found as a whole word in ``text`` (longest first)."""
    for term in BANNED_TERMS:
        if _TERM_RE[term].search(text):
            return term
    return None


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """ids() of ``ast.Constant`` nodes that are module/class/function docstrings.

    A docstring is the first statement of a module/class/function body when it
    is an ``ast.Expr`` wrapping a string ``Constant``. Such nodes are prose and
    must be excluded from string-literal scanning.
    """
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))
    return docstrings


def _code_strings_for_file(path: str) -> list[tuple[int, str, str]]:
    """``(lineno, term, snippet)`` for banned terms in identifiers / literals.

    Scans CODE only: identifiers (names, attributes, args, def/class names,
    import module + alias names) and non-docstring string-literal Constants.
    Comments are absent from the AST; docstrings are excluded explicitly.
    """
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source, filename=path)
    docstring_ids = _docstring_nodes(tree)
    hits: list[tuple[int, str, str]] = []

    def record(text: str, lineno: int) -> None:
        term = _matched_term(text)
        if term is not None:
            hits.append((lineno, term, text))

    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", 0)
        if isinstance(node, ast.Name):
            record(node.id, lineno)
        elif isinstance(node, ast.Attribute):
            record(node.attr, lineno)
        elif isinstance(node, ast.arg):
            record(node.arg, lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            record(node.name, lineno)
        elif isinstance(node, ast.keyword) and node.arg is not None:
            record(node.arg, lineno)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                record(alias.name, lineno)
                if alias.asname:
                    record(alias.asname, lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                record(node.module, lineno)
            for alias in node.names:
                record(alias.name, lineno)
                if alias.asname:
                    record(alias.asname, lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstring_ids:
                record(node.value, lineno)
    return hits


def _core_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    backend_root = os.path.dirname(os.path.dirname(here))
    return os.path.join(backend_root, "vbwd")


def _iter_core_python_files():
    root = _core_root()
    for dirpath, _dirs, files in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for filename in files:
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)


def _findings() -> list[tuple[str, int, str, str]]:
    """``(relpath, lineno, term, snippet)`` for every banned term in core CODE."""
    root_parent = os.path.dirname(_core_root())
    found: list[tuple[str, int, str, str]] = []
    for path in _iter_core_python_files():
        rel = os.path.relpath(path, root_parent)
        for lineno, term, snippet in _code_strings_for_file(path):
            if (rel, term) in ALLOWLIST:
                continue
            found.append((rel, lineno, term, snippet))
    return found


def test_core_has_no_domain_vocabulary():
    findings = _findings()
    if not ENFORCING:
        # Report mode: surface the landscape, never fail.
        by_term: dict[str, int] = {}
        for _rel, _ln, term, _txt in findings:
            by_term[term] = by_term.get(term, 0) + 1
        print(
            "\n[S50 vocabulary oracle — REPORT MODE] "
            f"{len(findings)} CODE hit(s) across core:\n  "
            + "\n  ".join(f"{t}: {n}" for t, n in sorted(by_term.items()))
        )
        for rel, lineno, term, txt in findings:
            print(f"  {rel}:{lineno} [{term}] {txt!r}")
        return
    assert not findings, (
        "Core (`vbwd/`) must name no plugin domain vocabulary in code. Found "
        f"{len(findings)} occurrence(s):\n  - "
        + "\n  - ".join(
            f"{rel}:{ln} [{term}] {txt!r}" for rel, ln, term, txt in findings
        )
    )


def test_oracle_scans_code_not_prose():
    """Self-test for refinement 1: a banned term as an identifier IS flagged,
    but the same word inside a comment/docstring is NOT (proves code-only)."""
    import tempfile

    code_snippet = (
        '"""Module docstring mentioning tarif_plan should be ignored."""\n'
        "# comment mentioning tarif_plan should be ignored\n"
        "def fetch():\n"
        '    """Helper docstring naming tarif_plan stays clean."""\n'
        "    label = 'just text'  # no banned literal here\n"
        "    return label\n"
    )
    flagged_snippet = "tarif_plan = load()\n"

    for snippet, expect_hit in ((code_snippet, False), (flagged_snippet, True)):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(snippet)
            tmp_path = handle.name
        try:
            hits = _code_strings_for_file(tmp_path)
        finally:
            os.unlink(tmp_path)
        has_hit = any(term == "tarif_plan" for _ln, term, _txt in hits)
        assert has_hit is expect_hit, (snippet, hits)
