"""Plugin-system error types."""


class PluginDependencyError(ValueError):
    """Raised when a plugin's declared dependency is unmet.

    Subclasses :class:`ValueError` so that every existing ``except ValueError``
    around plugin enable continues to work unchanged (a Liskov guarantee);
    callers that want the version-specific reason catch this subclass.
    """


class PluginLicenseError(ValueError):
    """Raised when a licence-requiring plugin has no covering licence.

    Subclasses :class:`ValueError` for the same Liskov reason as
    :class:`PluginDependencyError`: existing ``except ValueError`` callers around
    plugin enable keep working, and the plugin simply stays disabled.
    """

    def __init__(self, plugin_name: str, features: tuple) -> None:
        self.plugin_name = plugin_name
        self.features = features
        super().__init__(
            f"Plugin '{plugin_name}' requires a licence covering one of "
            f"{list(features)!r} — no covering key is held, so it will not be "
            f"activated."
        )


class PluginConfigurationError(Exception):
    """Raised by ``BasePlugin.validate_environment`` for a fatal misconfiguration.

    Deliberately NOT a :class:`ValueError` subclass: existing
    ``except ValueError`` callers around plugin enable must never swallow it.
    At boot it propagates out of ``PluginManager.load_persisted_state`` so
    ``create_app()`` fails and the process exits non-zero; on runtime enable
    the admin API maps it to a 4xx and the plugin stays disabled.

    Message convention: ``"<plugin>: <what is wrong> — <how to fix it>"``.
    """
