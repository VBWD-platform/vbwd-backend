"""Generic file-storage abstraction.

Any plugin that needs to persist binary blobs (images, attachments, exports,
etc.) depends on `IFileStorage` here, never on a specific plugin's storage
implementation.

As of Sprint 58.3 the production implementation is a thin adapter over the
unified :class:`~vbwd.services.filesystem.IFilesystemManager` ``uploads``
namespace, so there is **one** home for path confinement, write policy and
served-URL mapping. Two implementations are provided:

  * `ManagerBackedFileStorage` — adapter over the FilesystemManager (production).
  * `InMemoryFileStorage` — in-process dict, for unit tests that do not want to
    construct a manager.
"""
from abc import ABC, abstractmethod
from typing import Any

UPLOADS_NAMESPACE = "uploads"


class IFileStorage(ABC):
    """Interface for file storage backends."""

    @abstractmethod
    def save(self, file_data: bytes, relative_path: str) -> str:
        """Save file data to storage. Returns the relative path stored."""

    @abstractmethod
    def delete(self, relative_path: str) -> None:
        """Delete file at relative_path from storage."""

    @abstractmethod
    def get_url(self, relative_path: str) -> str:
        """Return the public URL for relative_path."""

    @abstractmethod
    def exists(self, relative_path: str) -> bool:
        """Return True if the file exists in storage."""

    @abstractmethod
    def read(self, relative_path: str) -> bytes:
        """Return raw bytes of a stored file."""


class ManagerBackedFileStorage(IFileStorage):
    """`IFileStorage` adapter over the unified FilesystemManager (Sprint 58.3).

    All operations route to the manager's ``uploads`` namespace, so on-disk
    paths (``<uploads_root>/<relative_path>``) and served URLs
    (``<UPLOADS_BASE_URL>/<relative_path>``) are identical to the legacy
    ``LocalFileStorage`` it replaces. Confinement now comes from the namespace
    (realpath-within-namespace — stronger than the old ``startswith`` guard,
    which a symlink could defeat).

    Consumers resolve the manager via ``container.filesystem_manager()`` and
    wrap it here, keeping their existing ``IFileStorage`` call-sites unchanged.
    """

    def __init__(self, filesystem_manager: Any) -> None:
        self._filesystem_manager = filesystem_manager

    def save(self, file_data: bytes, relative_path: str) -> str:
        return self._filesystem_manager.write_bytes(
            UPLOADS_NAMESPACE, relative_path, file_data
        )

    def delete(self, relative_path: str) -> None:
        self._filesystem_manager.delete(UPLOADS_NAMESPACE, relative_path)

    def get_url(self, relative_path: str) -> str:
        return self._filesystem_manager.url_for(UPLOADS_NAMESPACE, relative_path)

    def exists(self, relative_path: str) -> bool:
        return self._filesystem_manager.exists(UPLOADS_NAMESPACE, relative_path)

    def read(self, relative_path: str) -> bytes:
        return self._filesystem_manager.read_bytes(UPLOADS_NAMESPACE, relative_path)


class InMemoryFileStorage(IFileStorage):
    """In-memory storage for unit tests — no disk I/O."""

    def __init__(self, base_url: str = "/uploads") -> None:
        self.base_url = base_url.rstrip("/")
        self._store: dict[str, bytes] = {}

    def save(self, file_data: bytes, relative_path: str) -> str:
        self._store[relative_path] = file_data
        return relative_path

    def delete(self, relative_path: str) -> None:
        self._store.pop(relative_path, None)

    def get_url(self, relative_path: str) -> str:
        relative_path = relative_path.lstrip("/")
        return f"{self.base_url}/{relative_path}"

    def exists(self, relative_path: str) -> bool:
        return relative_path in self._store

    def read(self, relative_path: str) -> bytes:
        if relative_path not in self._store:
            raise FileNotFoundError(relative_path)
        return self._store[relative_path]
