"""Demo plugin — validates the external plugin system."""
from typing import Optional, TYPE_CHECKING
from vbwd.plugins.base import BasePlugin, PluginMetadata

if TYPE_CHECKING:
    from flask import Blueprint


class DemoPlugin(BasePlugin):
    """
    Demo plugin that exposes a simple authenticated endpoint.

    Returns {"success": true} when enabled, 404 when disabled.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="backend-demo-plugin",
            version="26.6",
            author="VBWD Team",
            description="Demo plugin — returns success on authenticated request",
            dependencies=[],
        )

    def get_blueprint(self) -> Optional["Blueprint"]:
        from plugins.demoplugin.routes import demo_plugin_bp

        return demo_plugin_bp

    def get_url_prefix(self) -> Optional[str]:
        return "/api/v1/backend-demo-plugin"

    def on_enable(self) -> None:
        pass

    def on_disable(self) -> None:
        pass
