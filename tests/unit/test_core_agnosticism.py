"""S01 oracle — core must not import from any plugin.

The CORE (`vbwd/`) must be agnostic of every plugin. The narrow violation
this test catches is direct ``from plugins.<name>...`` or ``import plugins.<name>``
imports inside core source. Plugin-to-plugin imports are allowed (declared via
``PluginMetadata.dependencies``); core-to-plugin imports are not.

Until S01 lands, this test fails on:
  - vbwd/scheduler.py — `from plugins.booking.booking...` (×3)
  - vbwd/routes/admin/access.py — `from plugins.cms.src.models...` (×2)
"""
import ast
import os


def _core_root() -> str:
    """Absolute path to ``vbwd-backend/vbwd/``."""
    here = os.path.dirname(os.path.abspath(__file__))
    backend_root = os.path.dirname(os.path.dirname(here))
    return os.path.join(backend_root, "vbwd")


def _iter_core_python_files():
    """Yield every `.py` file under ``vbwd/`` excluding caches."""
    root = _core_root()
    for dirpath, _dirs, files in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for filename in files:
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)


def _plugin_imports_in(file_path: str) -> list[tuple[int, str]]:
    """Return ``(lineno, module)`` for every ``plugins.*`` import in the file."""
    with open(file_path, encoding="utf-8") as handle:
        source = handle.read()
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "plugins" or module.startswith("plugins."):
                offenders.append((node.lineno, f"from {module} import …"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "plugins" or alias.name.startswith("plugins."):
                    offenders.append((node.lineno, f"import {alias.name}"))
    return offenders


def test_core_has_no_plugin_imports():
    """The exit gate for S01: zero ``plugins.*`` imports anywhere under ``vbwd/``."""
    findings: list[str] = []
    for path in _iter_core_python_files():
        for lineno, statement in _plugin_imports_in(path):
            rel = os.path.relpath(path, os.path.dirname(_core_root()))
            findings.append(f"{rel}:{lineno} — {statement}")
    assert not findings, (
        "Core (`vbwd/`) must be plugin-agnostic. Found "
        f"{len(findings)} forbidden import(s):\n  - " + "\n  - ".join(findings)
    )
