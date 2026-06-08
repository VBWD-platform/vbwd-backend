"""Ports and value objects for the unified FilesystemManager (Sprint 58.0).

The manager is agnostic core infrastructure: it routes *files*, never domains,
so it satisfies the core-agnosticism oracle. Consumers (core settings, plugin
manifests, SEO, uploads, secrets, logs) depend on :class:`IFilesystemManager`
and resolve it through the DI container — never on a sibling implementation.

A namespace is a logically isolated subtree (``core``, ``plugins``, ``seo`` …)
with its own :class:`NamespacePolicy` (write mode, permissions, encryption,
root, optional public URL base). All operations are addressed by
``(namespace, relative_path)``; the manager resolves + confines the path once,
centrally (D3).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


class WriteMode(enum.Enum):
    """Per-namespace write strategy (D2).

    * ``ATOMIC_REPLACE`` — temp file in the same dir, fsync, ``os.replace``.
      Crash-safe, no torn reads. Default for settings/SEO/secrets/uploads.
    * ``INPLACE_LOCKED`` — for bind-mounted single files where ``os.replace``
      fails with "Device or resource busy": advisory ``flock`` + truncate +
      rewrite in place, preserving the inode. Used for plugin manifests.
    * ``APPEND`` — ``O_APPEND`` under a short exclusive lock; used for logs.
    """

    ATOMIC_REPLACE = "atomic_replace"
    INPLACE_LOCKED = "inplace_locked"
    APPEND = "append"


@dataclass(frozen=True)
class NamespacePolicy:
    """Immutable policy describing how one namespace is stored.

    Attributes:
        write_mode: which :class:`WriteMode` writes in this namespace use.
        dir_mode: octal permission bits for directories created here.
        file_mode: octal permission bits applied to written files.
        encrypt: when True, file contents are encrypted at rest via the
            process cipher (used by the ``secrets`` namespace).
        base_root: which managed root this namespace lives under
            (``"var"`` or ``"uploads"``).
        url_base: public URL prefix for ``url_for`` (e.g. uploads); ``None``
            for namespaces that are never served over HTTP.
    """

    write_mode: WriteMode
    dir_mode: int
    file_mode: int
    encrypt: bool
    base_root: str
    url_base: Optional[str] = None


@runtime_checkable
class IFilesystemManager(Protocol):
    """The single, safe way to touch the managed tree.

    Every method takes a ``namespace`` and a ``relative_path`` (``rel``); the
    implementation confines the path within the namespace before any I/O.
    """

    def read_text(self, namespace: str, relative_path: str) -> str:
        """Return the decoded UTF-8 contents of a file."""
        ...

    def read_bytes(self, namespace: str, relative_path: str) -> bytes:
        """Return the raw bytes of a file."""
        ...

    def write_text(self, namespace: str, relative_path: str, text: str) -> str:
        """Persist ``text`` per the namespace policy; return ``relative_path``."""
        ...

    def write_bytes(self, namespace: str, relative_path: str, data: bytes) -> str:
        """Persist ``data`` per the namespace policy; return ``relative_path``."""
        ...

    def read_json(self, namespace: str, relative_path: str, default: Any = None) -> Any:
        """Load JSON; return ``default`` on a missing or corrupt file."""
        ...

    def write_json(self, namespace: str, relative_path: str, obj: Any) -> str:
        """Serialise ``obj`` to pretty JSON and persist it; return ``relative_path``."""
        ...

    def append_text(self, namespace: str, relative_path: str, text: str) -> None:
        """Append ``text`` to a file (log lines); creates it if missing."""
        ...

    def append_with_rotation(
        self,
        namespace: str,
        relative_path: str,
        text: str,
        max_bytes: int,
        backups: int,
    ) -> None:
        """Append ``text``, rotating the file to ``.1`` (keeping ``backups``)
        when it would exceed ``max_bytes``. The size check and the roll happen
        under the same exclusive lock as the append so concurrent gunicorn
        workers never double-rotate or interleave a line (Sprint 58.5)."""
        ...

    def delete(self, namespace: str, relative_path: str) -> None:
        """Remove a file; a no-op if it does not exist."""
        ...

    def exists(self, namespace: str, relative_path: str) -> bool:
        """Return True if the file exists."""
        ...

    def listdir(self, namespace: str, relative_path: str = "") -> list[str]:
        """Return the entry names directly under ``relative_path``."""
        ...

    def url_for(self, namespace: str, relative_path: str) -> str:
        """Return the public URL for a served file; raise if not served."""
        ...

    def resolve(self, namespace: str, relative_path: str) -> str:
        """Return the confined absolute path WITHOUT requiring it to exist."""
        ...
