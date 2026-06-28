"""Plugin dependency satisfaction + ordering.

The :class:`DependencyResolver` is the single home for deciding whether a
plugin's declared dependencies are met (presence + ENABLED + version range) and
for topologically ordering a set of plugins by those dependencies. The
:class:`~vbwd.plugins.manager.PluginManager` orchestrates lifecycle and reuses
one resolver across ``enable_plugin``, ``load_persisted_state``, the admin API,
and the CLI (DRY/SRP/DI). It names no plugin (core stays agnostic).
"""
import logging
from typing import Callable, Dict, List, Optional

from vbwd.plugins.base import BasePlugin, PluginStatus
from vbwd.plugins.errors import PluginDependencyError
from vbwd.plugins.versioning import DependencyRequirement, parse_dependency

logger = logging.getLogger(__name__)

GetPlugin = Callable[[str], Optional[BasePlugin]]


class DependencyResolver:
    """Decides dependency satisfaction and enable ordering for plugins."""

    def check(self, plugin: BasePlugin, get_plugin: GetPlugin) -> None:
        """Raise :class:`PluginDependencyError` if any dependency is unmet.

        For each declared dependency: the dependency plugin must be registered
        and ENABLED; if a version specifier is present, the dependency's
        ``metadata.version`` must satisfy it. A bare name ignores the version.
        """
        plugin_name = plugin.metadata.name
        for raw_dependency in plugin.metadata.dependencies or []:
            requirement = parse_dependency(raw_dependency)
            dependency_plugin = get_plugin(requirement.name)

            if (
                dependency_plugin is None
                or dependency_plugin.status != PluginStatus.ENABLED
            ):
                raise PluginDependencyError(
                    f"Cannot enable '{plugin_name}': dependency "
                    f"'{requirement.name}' is not enabled"
                )

            if str(requirement.specifier) and not requirement.is_satisfied_by(
                dependency_plugin.metadata.version
            ):
                raise PluginDependencyError(
                    f"Cannot enable '{plugin_name}': requires "
                    f"'{requirement.name}{requirement.specifier}' but "
                    f"'{requirement.name}' v{dependency_plugin.metadata.version} "
                    f"is installed"
                )

    def describe(
        self, plugin: BasePlugin, get_plugin: GetPlugin
    ) -> List[Dict[str, object]]:
        """Return per-dependency descriptors for the admin API.

        Each descriptor: ``{name, specifier, installed_version, satisfied}``
        where ``installed_version`` is the dependency's metadata version (or
        ``None`` if not registered) and ``satisfied`` is False when the
        dependency is missing/not-enabled or its version does not satisfy the
        specifier.
        """
        descriptors: List[Dict[str, object]] = []
        for raw_dependency in plugin.metadata.dependencies or []:
            requirement = parse_dependency(raw_dependency)
            dependency_plugin = get_plugin(requirement.name)
            installed_version = (
                dependency_plugin.metadata.version if dependency_plugin else None
            )
            descriptors.append(
                {
                    "name": requirement.name,
                    "specifier": str(requirement.specifier),
                    "installed_version": installed_version,
                    "satisfied": self._is_satisfied(requirement, dependency_plugin),
                }
            )
        return descriptors

    def enable_order(self, plugins: List[BasePlugin]) -> List[str]:
        """Topologically sort plugin names so a dependency precedes its dependent.

        Only dependencies that are themselves in ``plugins`` constrain the order
        (external/already-enabled dependencies are ignored here). Input order is
        otherwise preserved. A dependency cycle is logged as a deterministic
        error and the remaining plugins are appended in input order rather than
        crashing.
        """
        name_to_plugin = {plugin.metadata.name: plugin for plugin in plugins}
        in_set_dependencies: Dict[str, set] = {}
        for plugin in plugins:
            dependencies = set()
            for raw_dependency in plugin.metadata.dependencies or []:
                try:
                    requirement = parse_dependency(raw_dependency)
                except ValueError:
                    continue
                if requirement.name in name_to_plugin:
                    dependencies.add(requirement.name)
            in_set_dependencies[plugin.metadata.name] = dependencies

        ordered: List[str] = []
        resolved: set = set()
        remaining = [plugin.metadata.name for plugin in plugins]
        made_progress = True
        while remaining and made_progress:
            made_progress = False
            still_blocked: List[str] = []
            for name in remaining:
                if in_set_dependencies[name] <= resolved:
                    ordered.append(name)
                    resolved.add(name)
                    made_progress = True
                else:
                    still_blocked.append(name)
            remaining = still_blocked

        if remaining:
            logger.error(
                "Cyclic plugin dependency detected among: %s", sorted(remaining)
            )
            ordered.extend(remaining)

        return ordered

    @staticmethod
    def _is_satisfied(
        requirement: DependencyRequirement,
        dependency_plugin: Optional[BasePlugin],
    ) -> bool:
        if (
            dependency_plugin is None
            or dependency_plugin.status != PluginStatus.ENABLED
        ):
            return False
        return requirement.is_satisfied_by(dependency_plugin.metadata.version)
