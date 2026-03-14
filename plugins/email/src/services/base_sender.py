"""IEmailSender interface and EmailMessage value object."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Protocol, runtime_checkable


@dataclass
class EmailMessage:
    """Immutable value object representing one outbound email."""

    to_address: str
    subject: str
    html_body: str
    text_body: str = ""
    from_address: str = ""
    from_name: str = ""
    reply_to: Optional[str] = None
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    headers: dict = field(default_factory=dict)


@runtime_checkable
class IEmailSender(Protocol):
    """Liskov-safe transport contract.

    All implementations MUST:
    - accept an EmailMessage and send exactly one email
    - raise EmailSendError on failure (never swallow)
    - expose sender_id for registry keying
    """

    @property
    def sender_id(self) -> str:
        """Unique identifier for this transport, e.g. 'smtp', 'mandrill'."""
        ...

    def send(self, message: EmailMessage) -> None:
        """Send *message*.  Raises EmailSendError on failure."""
        ...


class EmailSendError(Exception):
    """Raised when a transport cannot deliver the message."""
