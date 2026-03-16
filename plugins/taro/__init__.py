"""Tarot card reading plugin with LLM-powered interpretations."""
from typing import Optional, Dict, Any, TYPE_CHECKING
from src.plugins.base import BasePlugin, PluginMetadata

if TYPE_CHECKING:
    from flask import Blueprint


DEFAULT_CONFIG = {
    "llm_api_endpoint": "",
    "llm_api_key": "",
    "llm_model": "gpt-4",
    "llm_temperature": 0.8,
    "llm_max_tokens": 200,
    "session_duration_minutes": 30,
    "session_expiry_warning_minutes": 3,
    "base_session_tokens": 10,
    "follow_up_base_tokens": 5,
}


class TaroPlugin(BasePlugin):
    """Tarot card reading with AI-powered interpretations.

    Class MUST be defined in __init__.py (not re-exported) due to
    discovery check obj.__module__ != full_module in manager.py.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="taro",
            version="1.0.0",
            author="VBWD Team",
            description="Tarot card reading with LLM-powered interpretations",
            dependencies=[],
        )

    def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Initialize with defaults merged with provided config."""
        merged = {**DEFAULT_CONFIG}
        if config:
            merged.update(config)
        super().initialize(merged)

    def get_blueprint(self) -> Optional["Blueprint"]:
        from plugins.taro.src.routes import taro_bp

        return taro_bp

    def get_url_prefix(self) -> Optional[str]:
        return "/api/v1/taro"

    def on_enable(self) -> None:
        pass

    def on_disable(self) -> None:
        pass
