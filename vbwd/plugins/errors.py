"""Plugin-system error types."""


class PluginDependencyError(ValueError):
    """Raised when a plugin's declared dependency is unmet.

    Subclasses :class:`ValueError` so that every existing ``except ValueError``
    around plugin enable continues to work unchanged (a Liskov guarantee);
    callers that want the version-specific reason catch this subclass.
    """
