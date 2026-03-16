"""EmailSenderRegistry — DI container for swappable email transports."""
from __future__ import annotations
from typing import Dict, Optional

from plugins.email.src.services.base_sender import IEmailSender


class SenderNotFoundError(Exception):
    """Raised when the requested sender_id is not registered."""


class EmailSenderRegistry:
    """Holds named IEmailSender implementations.

    Usage
    -----
    registry = EmailSenderRegistry()
    registry.register(SmtpEmailSender(...))
    registry.set_active("smtp")
    registry.active().send(msg)
    """

    def __init__(self) -> None:
        self._senders: Dict[str, IEmailSender] = {}
        self._active_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, sender: IEmailSender) -> None:
        """Register *sender* under its sender_id.  Overwrites silently."""
        self._senders[sender.sender_id] = sender

    def unregister(self, sender_id: str) -> None:
        self._senders.pop(sender_id, None)
        if self._active_id == sender_id:
            self._active_id = None

    # ------------------------------------------------------------------
    # Active transport
    # ------------------------------------------------------------------

    def set_active(self, sender_id: str) -> None:
        if sender_id not in self._senders:
            raise SenderNotFoundError(f"No sender registered with id '{sender_id}'")
        self._active_id = sender_id

    def active(self) -> IEmailSender:
        """Return the active sender.  Raises SenderNotFoundError if none set."""
        if self._active_id is None:
            raise SenderNotFoundError("No active email sender configured")
        try:
            return self._senders[self._active_id]
        except KeyError:
            raise SenderNotFoundError(
                f"Active sender '{self._active_id}' is no longer registered"
            )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def active_id(self) -> Optional[str]:
        return self._active_id

    def registered_ids(self) -> list:
        return list(self._senders.keys())

    def has(self, sender_id: str) -> bool:
        return sender_id in self._senders
