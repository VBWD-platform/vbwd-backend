"""Print the plugin dependencies that are declared but not checked out.

Per-plugin CI clones only the plugin under test, so its declared peers must be
cloned alongside it — otherwise ``PluginManager`` refuses to enable it
("Cannot enable 'X': dependency 'Y' is not enabled"), its blueprint never
mounts, and every route test fails with 404 instead of the asserted status.

The dependency set used to be hand-maintained in the workflow and drifted from
what the plugins actually declare (``subscription`` gained a dependency on
``email``, which the map never picked up — that single gap broke the meinchat,
tarot, subscription and ghrm jobs). Reading ``PluginMetadata.dependencies``
directly keeps the clone-set honest.

Parsing is done with ``ast`` rather than by importing the plugin: at this point
in the job the plugin's own runtime dependencies are not installed yet, so
importing would fail.

Usage (from the backend root)::

    python ci/missing_plugin_deps.py                 # runtime deps only
    python ci/missing_plugin_deps.py --for meinchat  # + that plugin's test imports

``--for`` is scoped deliberately. Runtime ``dependencies`` are followed for
every plugin present (that closure is what PluginManager enforces), but
test-only sibling imports are read from the plugin under test alone. Following
the *dependencies'* test imports as well snowballs — it drags in a third of the
catalogue, including private repos CI cannot clone.

Dependencies are transitive, so the caller should loop: clone what is printed,
then run this again, until it prints nothing.
"""
import ast
import os
import sys

PLUGINS_ROOT = "plugins"


def _parse(init_path: str):
    try:
        with open(init_path, encoding="utf-8") as handle:
            return ast.parse(handle.read(), filename=init_path)
    except (OSError, SyntaxError) as exc:
        print(f"warning: cannot parse {init_path}: {exc}", file=sys.stderr)
        return None


def _called_name(node: ast.Call) -> str:
    """``PluginMetadata(...)`` and ``base.PluginMetadata(...)`` both -> the name."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _string_keyword(tree, keyword_name: str) -> list[str]:
    """String literals passed as ``keyword_name=...`` to ``PluginMetadata(...)``.

    Scoped to PluginMetadata on purpose: ``name=`` is a common keyword
    (Blueprint, columns, fields), and counting those as plugin names would make
    a genuinely missing dependency look present.

    Handles both ``name="x"`` (a bare string) and ``dependencies=["x", "y"]``
    (a list). Non-literal entries are skipped — they cannot be resolved without
    importing, and no plugin currently uses one.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _called_name(node) != "PluginMetadata":
            continue
        for keyword in node.keywords:
            if keyword.arg != keyword_name:
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                found.append(value.value)
            elif isinstance(value, ast.List):
                for element in value.elts:
                    if isinstance(element, ast.Constant) and isinstance(
                        element.value, str
                    ):
                        found.append(element.value)
    return found


def _imported_sibling_plugins(plugin_dir: str) -> set[str]:
    """Directory names this plugin imports as ``plugins.<name>``.

    Runtime metadata is not the whole story: several plugins' *tests* import a
    peer directly (subscription's bot-storefront tests import
    ``plugins.bot_base``, ghrm's import ``plugins.cms``). Those peers must be
    checked out too or the module fails to import and pytest reports a
    collection error rather than a test result. Unlike ``dependencies`` these
    are Python packages, so they name the directory, not the metadata name.
    """
    found: set[str] = set()
    for current_root, _dirs, files in os.walk(plugin_dir):
        for file_name in files:
            if not file_name.endswith(".py"):
                continue
            tree = _parse(os.path.join(current_root, file_name))
            if tree is None:
                continue
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    modules = [node.module or ""]
                for module in modules:
                    parts = module.split(".")
                    if len(parts) >= 2 and parts[0] == "plugins":
                        found.add(parts[1])
    return found


def main() -> int:
    if not os.path.isdir(PLUGINS_ROOT):
        print(f"error: no {PLUGINS_ROOT}/ directory here", file=sys.stderr)
        return 1

    # Dependencies name a plugin by its ``PluginMetadata.name`` (kebab, e.g.
    # "bot-base"), which is not always the directory (snake, "bot_base"). So
    # presence has to be judged by declared name, not by folder.
    present: set[str] = set()
    declared: set[str] = set()

    directories = [
        directory
        for directory in sorted(os.listdir(PLUGINS_ROOT))
        if os.path.isfile(os.path.join(PLUGINS_ROOT, directory, "__init__.py"))
    ]

    for directory in directories:
        tree = _parse(os.path.join(PLUGINS_ROOT, directory, "__init__.py"))
        if tree is None:
            continue
        present.add(directory)
        present.update(_string_keyword(tree, "name"))
        declared.update(_string_keyword(tree, "dependencies"))

    under_test = _plugin_under_test()
    if under_test and under_test in directories:
        declared.update(
            _imported_sibling_plugins(os.path.join(PLUGINS_ROOT, under_test))
        )

    for name in sorted(declared - present):
        print(name)
    return 0


def _plugin_under_test() -> str:
    """The ``--for <plugin>`` argument, or "" when not given."""
    argv = sys.argv[1:]
    if "--for" in argv:
        index = argv.index("--for")
        if index + 1 < len(argv):
            return argv[index + 1]
        print("error: --for needs a plugin directory name", file=sys.stderr)
        raise SystemExit(2)
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
