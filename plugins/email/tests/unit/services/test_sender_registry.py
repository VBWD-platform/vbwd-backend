"""Unit tests for EmailSenderRegistry."""
import pytest
from unittest.mock import MagicMock

from plugins.email.src.services.sender_registry import EmailSenderRegistry, SenderNotFoundError


def _make_sender(sender_id: str):
    mock = MagicMock()
    mock.sender_id = sender_id
    return mock


class TestEmailSenderRegistry:
    def test_register_and_set_active(self):
        registry = EmailSenderRegistry()
        sender = _make_sender("smtp")
        registry.register(sender)
        registry.set_active("smtp")
        assert registry.active() is sender

    def test_active_id(self):
        registry = EmailSenderRegistry()
        registry.register(_make_sender("smtp"))
        registry.set_active("smtp")
        assert registry.active_id == "smtp"

    def test_registered_ids(self):
        registry = EmailSenderRegistry()
        registry.register(_make_sender("smtp"))
        registry.register(_make_sender("mandrill"))
        assert set(registry.registered_ids()) == {"smtp", "mandrill"}

    def test_has(self):
        registry = EmailSenderRegistry()
        registry.register(_make_sender("smtp"))
        assert registry.has("smtp")
        assert not registry.has("mandrill")

    def test_set_active_unknown_raises(self):
        registry = EmailSenderRegistry()
        with pytest.raises(SenderNotFoundError):
            registry.set_active("nonexistent")

    def test_active_without_set_raises(self):
        registry = EmailSenderRegistry()
        registry.register(_make_sender("smtp"))
        with pytest.raises(SenderNotFoundError):
            registry.active()

    def test_unregister_clears_active(self):
        registry = EmailSenderRegistry()
        registry.register(_make_sender("smtp"))
        registry.set_active("smtp")
        registry.unregister("smtp")
        assert registry.active_id is None
        with pytest.raises(SenderNotFoundError):
            registry.active()

    def test_register_overwrites(self):
        registry = EmailSenderRegistry()
        first = _make_sender("smtp")
        second = _make_sender("smtp")
        registry.register(first)
        registry.register(second)
        registry.set_active("smtp")
        assert registry.active() is second
