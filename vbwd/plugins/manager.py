"""Plugin manager for loading and managing plugins."""
import importlib
import inspect
import logging
import pkgutil
from typing import Dict, List, Optional
from vbwd.plugins.base import BasePlugin, PluginStatus
from vbwd.plugins.config_store import PluginConfigStore
from vbwd.plugins.dependency_resolver import DependencyResolver
from vbwd.plugins.errors import PluginDependencyError
from vbwd.events.dispatcher import EventDispatcher, Event

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
        dependency_resolver: Optional[DependencyResolver] = None,
    ):
        self._plugins: Dict[str, BasePlugin] = {}
        self._event_dispatcher = event_dispatcher or EventDispatcher()
        self._config_repo = config_repo
        self._category_service = category_service
        self._dependency_resolver = dependency_resolver or DependencyResolver()

    @property
    def dependency_resolver(self) -> DependencyResolver:
        """Expose the dependency resolver (reused by routes/CLI for DRY)."""
        return self._dependency_resolver

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

        # Check dependencies (presence + ENABLED + version range).
        # Raises PluginDependencyError (a ValueError subtype, so existing
        # ``except ValueError`` callers are unaffected).
        self._dependency_resolver.check(plugin, self.get_plugin)

        plugin.enable()

        # Wire event + line-item handlers after on_enable() has run
        self._wire_runtime_handlers(plugin)

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

        # Persist state (stamp the real metadata version, not a hardcoded pin)
        if self._config_repo:
            try:
                self._config_repo.save(
                    name, "enabled", plugin._config, version=plugin.metadata.version
                )
            except Exception as e:
                logger.warning(f"Failed to persist enable state for '{name}': {e}")

        # Emit event
        event = Event(name="plugin.enabled", data={"plugin_name": name})
        self._event_dispatcher.dispatch(event)

    def _wire_runtime_handlers(self, plugin: BasePlugin) -> None:
        """Subscribe a freshly enabled plugin to the event bus + line items.

        Shared by ``enable_plugin`` and ``load_persisted_state`` (DRY). A
        plugin that is skipped at the dependency gate never reaches here, so
        no handlers are wired for a half-enabled plugin.
        """
        name = plugin.metadata.name
        try:
            from vbwd.events.bus import event_bus

            plugin.register_event_handlers(event_bus)

            from vbwd.events.line_item_registry import line_item_registry

            plugin.register_line_item_handlers(line_item_registry)
        except Exception as handler_error:
            logger.warning(
                f"Failed to register event handlers for plugin '{name}': "
                f"{handler_error}"
            )

    def _reconcile_version_pin(self, plugin: BasePlugin, entry) -> None:
        """Self-heal the persisted manifest pin to the loaded code version.

        Code metadata always wins; the manifest pin is an observability signal
        only. ``enable_plugin`` already stamps the real metadata version, but a
        plugin enabled at boot via ``load_persisted_state`` keeps whatever pin
        was seeded into ``plugins.json`` — typically a stale placeholder
        (``1.0.0``) that never matches the shared code version. Left alone that
        drift re-emits a WARNING for every plugin on every boot forever.

        Instead, when the pin differs we re-stamp it to the loaded version (the
        same write ``enable_plugin`` performs) so it converges to silence. A
        single INFO records the reconciliation; genuine code-version changes
        under a fixed pin still surface once, then quiet down.
        """
        if entry is None:
            return
        pinned_version = getattr(entry, "version", None)
        if not pinned_version:
            return
        loaded_version = plugin.metadata.version
        if pinned_version == loaded_version:
            return

        name = plugin.metadata.name
        logger.info(
            "Plugin '%s' manifest pin %s reconciled to loaded code version %s",
            name,
            pinned_version,
            loaded_version,
        )
        if self._config_repo:
            try:
                self._config_repo.save(name, "enabled", version=loaded_version)
            except Exception as persist_error:
                logger.warning(
                    "Failed to reconcile version pin for '%s': %s",
                    name,
                    persist_error,
                )

    # S25 — removed ``get_plugin_blueprints``: zero production callers.
    # ``vbwd/app.py`` iterates ``get_all_plugins()`` directly and calls
    # ``plugin.get_blueprint()`` itself, so this helper only existed to
    # satisfy its own dedicated test file (now deleted with it).

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

        # Persist state (stamp the real metadata version, not a hardcoded pin)
        if self._config_repo:
            try:
                self._config_repo.save(
                    name, "disabled", plugin._config, version=plugin.metadata.version
                )
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
        """Load plugin enabled/disabled state from the persisted store.

        Persisted-enabled plugins are topologically ordered (so a dependency
        enables before its dependent regardless of stored order) and run the
        same dependency gate as ``enable_plugin``. A plugin whose dependency is
        missing/disabled or whose version is too old is logged as a WARNING and
        left DISABLED — never half-wired.
        """
        if not self._config_repo:
            return

        try:
            enabled_configs = self._config_repo.get_enabled()
        except Exception as e:
            logger.warning(f"Failed to load persisted plugin state: {e}")
            return

        entries_by_name: Dict[str, object] = {}
        pending_plugins: List[BasePlugin] = []
        for config in enabled_configs:
            plugin = self.get_plugin(config.plugin_name)
            if not plugin:
                logger.warning(
                    f"Persisted plugin '{config.plugin_name}' not found in "
                    f"registry, skipping"
                )
                continue
            entries_by_name[config.plugin_name] = config
            if plugin.status == PluginStatus.INITIALIZED:
                pending_plugins.append(plugin)

        for plugin_name in self._dependency_resolver.enable_order(pending_plugins):
            plugin = self.get_plugin(plugin_name)
            if not plugin:
                continue
            entry = entries_by_name.get(plugin_name)

            try:
                stored_config = getattr(entry, "config", None)
                if stored_config:
                    plugin.initialize(stored_config)
            except Exception as init_error:
                logger.warning(
                    f"Failed to initialize plugin '{plugin_name}': {init_error}"
                )
                continue

            self._reconcile_version_pin(plugin, entry)

            try:
                self._dependency_resolver.check(plugin, self.get_plugin)
            except PluginDependencyError as dependency_error:
                logger.warning(
                    "Skipping persisted plugin '%s': %s",
                    plugin_name,
                    dependency_error,
                )
                continue

            try:
                plugin.enable()
                self._wire_runtime_handlers(plugin)
                logger.info(f"Restored enabled state for plugin '{plugin_name}'")
            except Exception as e:
                logger.warning(f"Failed to restore plugin '{plugin_name}': {e}")
