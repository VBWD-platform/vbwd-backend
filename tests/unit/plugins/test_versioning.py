"""Tests for the pure plugin version/dependency-spec parser (S108.0)."""
import pytest
from packaging.specifiers import SpecifierSet

from vbwd.plugins.versioning import DependencyRequirement, parse_dependency


class TestParseDependency:
    """parse_dependency turns a ``name<specifier>`` string into a requirement."""

    def test_bare_name_matches_any_version(self):
        requirement = parse_dependency("email")
        assert requirement.name == "email"
        assert requirement.is_satisfied_by("26.6") is True
        assert requirement.is_satisfied_by("1.0.0") is True

    def test_greater_or_equal_specifier(self):
        requirement = parse_dependency("email>=26.7")
        assert requirement.name == "email"
        assert requirement.specifier == SpecifierSet(">=26.7")
        assert requirement.is_satisfied_by("26.7") is True
        assert requirement.is_satisfied_by("26.8") is True
        assert requirement.is_satisfied_by("26.6") is False

    def test_compatible_release_specifier(self):
        requirement = parse_dependency("cms~=26.6")
        assert requirement.name == "cms"
        assert requirement.is_satisfied_by("26.6") is True
        assert requirement.is_satisfied_by("26.9") is True
        assert requirement.is_satisfied_by("27.0") is False

    def test_exact_match_specifier(self):
        requirement = parse_dependency("shop==26.6.1")
        assert requirement.name == "shop"
        assert requirement.is_satisfied_by("26.6.1") is True
        assert requirement.is_satisfied_by("26.6.2") is False

    def test_not_equal_specifier(self):
        requirement = parse_dependency("email!=26.6")
        assert requirement.name == "email"
        assert requirement.is_satisfied_by("26.6") is False
        assert requirement.is_satisfied_by("26.7") is True

    def test_multi_specifier(self):
        requirement = parse_dependency("email>=26.6,<27")
        assert requirement.name == "email"
        assert requirement.is_satisfied_by("26.6") is True
        assert requirement.is_satisfied_by("26.9") is True
        assert requirement.is_satisfied_by("27.0") is False
        assert requirement.is_satisfied_by("26.5") is False

    def test_whitespace_tolerant(self):
        requirement = parse_dependency(" email >= 26.7 ")
        assert requirement.name == "email"
        assert requirement.is_satisfied_by("26.7") is True
        assert requirement.is_satisfied_by("26.6") is False

    def test_invalid_specifier_raises_value_error_naming_token(self):
        with pytest.raises(ValueError) as excinfo:
            parse_dependency("email=>26")
        assert "=>26" in str(excinfo.value)

    def test_empty_dependency_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_dependency("   ")

    def test_unparseable_version_does_not_satisfy(self):
        requirement = parse_dependency("email>=26.7")
        assert requirement.is_satisfied_by("not-a-version") is False

    def test_returns_dependency_requirement_instance(self):
        requirement = parse_dependency("email")
        assert isinstance(requirement, DependencyRequirement)


class TestNoImportCycle:
    """The module must not import the manager (no cycle) and name no plugin."""

    def test_module_does_not_import_manager(self):
        import ast
        import inspect
        import vbwd.plugins.versioning as versioning_module

        tree = ast.parse(inspect.getsource(versioning_module))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        assert "vbwd.plugins.manager" not in imported_modules
