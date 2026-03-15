"""Plugin base classes and interfaces."""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from enum import Enum
from dataclasses import dataclass

if TYPE_CHECKING:
    from flask import Blueprint


class PluginStatus(Enum):
    """Plugin status."""

    DISCOVERED = "discovered"
    REGISTERED = "registered"
    INITIALIZED = "initialized"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class PluginMetadata:
    """Plugin metadata."""

    name: str
    version: str
    author: str
    description: str
    dependencies: Optional[List[str]] = None

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


class BasePlugin(ABC):
    """
    Base class for all plugins.

    Plugins must inherit from this class and implement required methods.
    """

    def __init__(self):
        self._status = PluginStatus.DISCOVERED
        self._config: Dict[str, Any] = {}

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        pass

    @property
    def status(self) -> PluginStatus:
        """Get plugin status."""
        return self._status

    def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize plugin with configuration.

        Args:
            config: Optional configuration dictionary
        """
        if config:
            self._config = config
        self._status = PluginStatus.INITIALIZED

    def enable(self) -> None:
        """Enable the plugin."""
        if self._status != PluginStatus.INITIALIZED:
            raise ValueError(f"Cannot enable plugin in {self._status.value} state")
        self.on_enable()
        self._status = PluginStatus.ENABLED

    def disable(self) -> None:
        """Disable the plugin."""
        if self._status != PluginStatus.ENABLED:
            raise ValueError(f"Cannot disable plugin in {self._status.value} state")
        self.on_disable()
        self._status = PluginStatus.DISABLED

    def on_enable(self) -> None:
        """Hook called when plugin is enabled."""
        pass

    def on_disable(self) -> None:
        """Hook called when plugin is disabled."""
        pass

    def get_blueprint(self) -> Optional["Blueprint"]:
        """Return Flask blueprint for this plugin's routes. None if no routes."""
        return None

    def get_url_prefix(self) -> Optional[str]:
        """Return URL prefix for this plugin's blueprint."""
        return None

    def get_admin_blueprint(self) -> Optional["Blueprint"]:
        """Return Flask blueprint for admin-specific routes. None if no admin routes."""
        return None

    def register_event_handlers(self, bus: Any) -> None:
        """Subscribe to EventBus events.

        Called by ``PluginManager.enable_plugin()`` after ``on_enable()``.
        Override this method to subscribe to domain or plugin events using
        ``bus.subscribe(event_name, callback)``.

        Args:
            bus: The ``EventBus`` singleton (typed as ``Any`` to avoid a
                 circular import; in practice always an ``EventBus`` instance).
        """
        pass

    def register_categories(self) -> List[Dict[str, Any]]:
        """
        Return category definitions to register on plugin enable.

        Each dict should have: name, slug, and optionally
        description, parent_slug, is_single, sort_order.

        Returns empty list by default (no categories).
        """
        return []

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self._config.get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        """Set configuration value."""
        self._config[key] = value
