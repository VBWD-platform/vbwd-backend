"""Unified FilesystemManager — agnostic core file-access infrastructure.

Sprint 58.0 keystone. One safe, testable way to touch the managed tree
(``${VBWD_VAR_DIR}`` namespaces + the uploads root). Consumers resolve
:class:`IFilesystemManager` through the DI container
(``container.filesystem_manager()``) and address files by
``(namespace, relative_path)``; the manager owns confinement, write policy,
permissions, optional encryption, and JSON/append helpers.
"""
from .local import LocalFilesystemManager, build_uploads_pinned_manager
from .memory import InMemoryFilesystemManager
from .ports import IFilesystemManager, NamespacePolicy, WriteMode

__all__ = [
    "IFilesystemManager",
    "NamespacePolicy",
    "WriteMode",
    "LocalFilesystemManager",
    "InMemoryFilesystemManager",
    "build_uploads_pinned_manager",
]
