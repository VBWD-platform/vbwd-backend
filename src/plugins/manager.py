"""Plugin manager for loading and managing plugins."""
import importlib
import inspect
import logging
import pkgutil
from typing import Dict, List, Optional, Tuple
from src.plugins.base import BasePlugin, PluginStatus
from src.plugins.config_store import PluginConfigStore
from src.events.dispatcher import EventDispatcher, Event

logger = logging.getLogger(__name__)


class PluginManager:
    """
    Plugin manager for loading and managing plugins.

    Handles plugin discovery, registration, lifecycle, and dependencies.
    """

    def __init__(
        self,
        event_dispatcher: Optional[EventDispatcher] = None,
        config_repo: Optional[PluginConfigStore] = None,
        category_service=None,
    ):
        self._plugins: Dict[str, BasePlugin] = {}
        self._event_dispatcher = event_dispatcher or EventDispatcher()
        self._config_repo = config_repo
        self._category_service = category_service

    @property
    def event_dispatcher(self) -> EventDispatcher:
        """Get event dispatcher."""
        return self._event_dispatcher

    def register_plugin(self, plugin: BasePlugin) -> None:
        """
        Register a plugin.

        Args:
            plugin: Plugin instance to register

        Raises:
            ValueError: If plugin already registered
        """
        name = plugin.metadata.name

        if name in self._plugins:
            raise ValueError(f"Plugin '{name}' already registered")

        self._plugins[name] = plugin

        # Emit event
        event = Event(name="plugin.registered", data={"plugin_name": name})
        self._event_dispatcher.dispatch(event)

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """Get plugin by name."""
        return self._plugins.get(name)

    def get_all_plugins(self) -> List[BasePlugin]:
        """Get all registered plugins."""
        return list(self._plugins.values())

    def get_enabled_plugins(self) -> List[BasePlugin]:
        """Get all enabled plugins."""
        return [
            plugin
            for plugin in self._plugins.values()
            if plugin.status == PluginStatus.ENABLED
        ]

    def initialize_plugin(
        self,
        name: str,
        config: Optional[Dict] = None,
    ) -> None:
        """
        Initialize plugin with configuration.

        Args:
            name: Plugin name
            config: Optional configuration

        Raises:
            ValueError: If plugin not found
        """
        plugin = self.get_plugin(name)
        if not plugin:
            raise ValueError(f"Plugin '{name}' not found")

        plugin.initialize(config)

        # Emit event
        event = Event(name="plugin.initialized", data={"plugin_name": name})
        self._event_dispatcher.dispatch(event)

    def enable_plugin(self, name: str) -> None:
        """
        Enable plugin.

        Args:
            name: Plugin name

        Raises:
            ValueError: If plugin not found or dependencies not met
        """
        plugin = self.get_plugin(name)
        if not plugin:
            raise ValueError(f"Plugin '{name}' not found")

        # Check dependencies
        for dep in plugin.metadata.dependencies or []:
            dep_plugin = self.get_plugin(dep)
            if not dep_plugin or dep_plugin.status != PluginStatus.ENABLED:
                raise ValueError(f"Dependency '{dep}' not enabled")

        plugin.enable()

        # Register plugin categories (idempotent)
        if self._category_service:
            for cat_def in plugin.register_categories():
                try:
                    existing = self._category_service.get_by_slug(cat_def["slug"])
                    if not existing:
                        self._category_service.create(
                            name=cat_def["name"],
                            slug=cat_def["slug"],
                            description=cat_def.get("description"),
                            is_single=cat_def.get("is_single", True),
                            sort_order=cat_def.get("sort_order", 0),
                        )
                        logger.info(
                            f"Registered category '{cat_def['slug']}' "
                            f"from plugin '{name}'"
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to register category '{cat_def.get('slug')}' "
                        f"from plugin '{name}': {e}"
                    )

        # Persist state
        if self._config_repo:
            try:
                self._config_repo.save(name, "enabled", plugin._config)
            except Exception as e:
                logger.warning(f"Failed to persist enable state for '{name}': {e}")

        # Emit event
        event = Event(name="plugin.enabled", data={"plugin_name": name})
        self._event_dispatcher.dispatch(event)

    def get_plugin_blueprints(self) -> List[Tuple]:
        """Get blueprints from all enabled plugins that provide routes."""
        result = []
        for plugin in self.get_enabled_plugins():
            bp = plugin.get_blueprint()
            if bp:
                result.append((bp, plugin.get_url_prefix()))
        return result

    def disable_plugin(self, name: str) -> None:
        """
        Disable plugin.

        Args:
            name: Plugin name

        Raises:
            ValueError: If plugin not found or other plugins depend on it
        """
        plugin = self.get_plugin(name)
        if not plugin:
            raise ValueError(f"Plugin '{name}' not found")

        # Check if other plugins depend on this one
        dependent_plugins = [
            p
            for p in self._plugins.values()
            if name in (p.metadata.dependencies or [])
            and p.status == PluginStatus.ENABLED
        ]

        if dependent_plugins:
            names = [p.metadata.name for p in dependent_plugins]
            raise ValueError(f"Cannot disable: plugins {names} depend on it")

        plugin.disable()

        # Persist state
        if self._config_repo:
            try:
                self._config_repo.save(name, "disabled", plugin._config)
            except Exception as e:
                logger.warning(f"Failed to persist disable state for '{name}': {e}")

        # Emit event
        event = Event(name="plugin.disabled", data={"plugin_name": name})
        self._event_dispatcher.dispatch(event)

    def discover(self, package_path: str) -> int:
        """
        Auto-discover and register plugins from a package.

        Scans the given package for BasePlugin subclasses,
        instantiates them, and registers + initializes them.

        Args:
            package_path: Dotted module path (e.g. 'src.plugins.providers')

        Returns:
            Number of newly discovered plugins.
        """
        # Normalize path separators
        module_path = package_path.replace("/", ".").rstrip(".")

        try:
            package = importlib.import_module(module_path)
        except ImportError as e:
            logger.warning(f"Failed to import package '{module_path}': {e}")
            return 0

        count = 0
        package_dir = getattr(package, "__path__", None)
        if not package_dir:
            return 0

        for _importer, module_name, _ispkg in pkgutil.iter_modules(package_dir):
            full_module = f"{module_path}.{module_name}"
            try:
                module = importlib.import_module(full_module)
            except Exception as e:
                logger.warning(f"Failed to import module '{full_module}': {e}")
                continue

            for _name, obj in inspect.getmembers(module, inspect.isclass):
                # Must be a BasePlugin subclass
                if not issubclass(obj, BasePlugin):
                    continue
                # Skip BasePlugin itself
                if obj is BasePlugin:
                    continue
                # Skip abstract classes
                if inspect.isabstract(obj):
                    continue
                # Skip classes imported from other modules
                if obj.__module__ != full_module:
                    continue
                # Skip already-registered plugins
                try:
                    instance = obj()
                    plugin_name = instance.metadata.name
                except Exception as e:
                    logger.warning(f"Failed to instantiate {obj.__name__}: {e}")
                    continue

                if plugin_name in self._plugins:
                    continue

                try:
                    self.register_plugin(instance)
                    self.initialize_plugin(plugin_name)
                    count += 1
                    logger.info(f"Discovered plugin: {plugin_name}")
                except Exception as e:
                    logger.warning(f"Failed to register plugin '{plugin_name}': {e}")

        return count

    def load_persisted_state(self) -> None:
        """Load plugin enabled/disabled state from the database."""
        if not self._config_repo:
            return

        try:
            enabled_configs = self._config_repo.get_enabled()
        except Exception as e:
            logger.warning(f"Failed to load persisted plugin state: {e}")
            return

        for config in enabled_configs:
            plugin = self.get_plugin(config.plugin_name)
            if not plugin:
                logger.warning(
                    f"Persisted plugin '{config.plugin_name}' not found in registry, skipping"
                )
                continue

            if plugin.status == PluginStatus.INITIALIZED:
                try:
                    if config.config:
                        plugin.initialize(config.config)
                    plugin.enable()
                    logger.info(
                        f"Restored enabled state for plugin '{config.plugin_name}'"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to restore plugin '{config.plugin_name}': {e}"
                    )
