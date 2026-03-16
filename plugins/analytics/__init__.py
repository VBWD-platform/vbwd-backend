"""Analytics plugin — provides active sessions count."""
from typing import Dict, Any, Optional, Callable, TYPE_CHECKING
from src.plugins.base import BasePlugin, PluginMetadata

if TYPE_CHECKING:
    from flask import Blueprint


class AnalyticsPlugin(BasePlugin):
    """
    Analytics plugin providing active sessions count.

    Count function is injected via config (DI principle).
    Routes and business logic live in src/ subdirectory.
    """

    def __init__(self):
        super().__init__()
        self._active = False
        self._count_fn: Optional[Callable[[], int]] = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="analytics",
            version="1.0.0",
            author="VBWD Team",
            description="Dashboard analytics widget — active sessions count",
            dependencies=[],
        )

    def get_blueprint(self) -> Optional["Blueprint"]:
        from plugins.analytics.src.routes import analytics_plugin_bp

        return analytics_plugin_bp

    def get_url_prefix(self) -> Optional[str]:
        return "/api/v1/plugins/analytics"

    def get_admin_blueprint(self) -> Optional["Blueprint"]:
        """Return the admin analytics blueprint for direct registration."""
        from plugins.analytics.src.routes import analytics_admin_bp

        return analytics_admin_bp

    def on_enable(self) -> None:
        self._active = True
        self._count_fn = self._config.get("session_count_fn")

    def on_disable(self) -> None:
        self._active = False
        self._count_fn = None

    def get_active_sessions(self) -> Dict[str, Any]:
        """Return active sessions count."""
        count = 0
        if self._count_fn:
            try:
                count = self._count_fn()
            except Exception:
                count = 0
        return {"count": count, "source": "plugin"}
