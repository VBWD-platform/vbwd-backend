"""Pure version + dependency-specifier parsing for the plugin system.

This module is intentionally free of Flask and of any import of
``vbwd.plugins.manager`` (so it introduces no import cycle) and it names no
plugin. It is a thin, focused wrapper over :mod:`packaging` that turns a
``name<specifier>`` dependency string into a :class:`DependencyRequirement`
and answers version-satisfaction questions.
"""
from dataclasses import dataclass

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

# Characters that can begin a PEP 440 version specifier (``>=``, ``~=`` ...).
_SPECIFIER_OPERATOR_CHARACTERS = frozenset("<>=!~")


@dataclass(frozen=True)
class DependencyRequirement:
    """A parsed plugin dependency: a plugin name plus an optional version range."""

    name: str
    specifier: SpecifierSet

    def is_satisfied_by(self, version_string: str) -> bool:
        """Return True if ``version_string`` satisfies this requirement.

        A bare requirement (empty specifier) is satisfied by any version. An
        unparseable version never satisfies a non-empty specifier.
        """
        if not str(self.specifier):
            return True
        try:
            return Version(version_string) in self.specifier
        except InvalidVersion:
            return False


def parse_dependency(raw_dependency: str) -> DependencyRequirement:
    """Parse a ``name<specifier>`` dependency string.

    Examples:
        ``"email"``        -> name ``email``, matches any version
        ``"email>=26.7"``  -> name ``email``, specifier ``>=26.7``
        ``"email>=26.6,<27"`` -> multi-clause specifier
        ``" email >= 26.7 "`` -> whitespace tolerant

    Raises:
        ValueError: if the dependency has no name or carries an invalid
            specifier (the offending token is named in the message).
    """
    text = raw_dependency.strip()
    if not text:
        raise ValueError("Empty dependency specification")

    split_index = None
    for index, character in enumerate(text):
        if character in _SPECIFIER_OPERATOR_CHARACTERS:
            split_index = index
            break

    if split_index is None:
        plugin_name = text
        specifier_text = ""
    else:
        plugin_name = text[:split_index].strip()
        specifier_text = text[split_index:].strip()

    if not plugin_name:
        raise ValueError(f"Dependency '{raw_dependency}' is missing a plugin name")

    try:
        specifier = SpecifierSet(specifier_text)
    except InvalidSpecifier as error:
        raise ValueError(
            f"Invalid version specifier '{specifier_text}' "
            f"in dependency '{raw_dependency}': {error}"
        ) from error

    return DependencyRequirement(name=plugin_name, specifier=specifier)
