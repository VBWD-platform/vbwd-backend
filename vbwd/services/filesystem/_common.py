"""Shared internals for the FilesystemManager implementations (Sprint 58.0).

Holds the single source of truth for:
  * the default namespace -> :class:`NamespacePolicy` table, and
  * the relative-path validation rules (reject absolute / ``..`` / NUL).

The on-disk realpath-within-namespace confinement (defeating symlink escape)
lives in :mod:`vbwd.services.filesystem.local`, because only the disk impl has
real paths to resolve; the in-memory impl shares the relative-path validation.
"""
from __future__ import annotations

import os
from typing import Dict, Optional

from .ports import NamespacePolicy, WriteMode

# Permission defaults, named so no magic numbers leak into call-sites.
DEFAULT_DIR_MODE = 0o755
DEFAULT_FILE_MODE = 0o644
SECRETS_DIR_MODE = 0o700
SECRETS_FILE_MODE = 0o600

VAR_ROOT_KEY = "var"
UPLOADS_ROOT_KEY = "uploads"


def build_default_namespaces(
    uploads_url_base: Optional[str],
) -> Dict[str, NamespacePolicy]:
    """Return the canonical namespace registry (the managed tree of D2/D4/D5).

    ``uploads_url_base`` is the public URL prefix uploads are served under.
    """
    return {
        "core": NamespacePolicy(
            write_mode=WriteMode.ATOMIC_REPLACE,
            dir_mode=DEFAULT_DIR_MODE,
            file_mode=DEFAULT_FILE_MODE,
            encrypt=False,
            base_root=VAR_ROOT_KEY,
        ),
        "plugins": NamespacePolicy(
            write_mode=WriteMode.INPLACE_LOCKED,
            dir_mode=DEFAULT_DIR_MODE,
            file_mode=DEFAULT_FILE_MODE,
            encrypt=False,
            base_root=VAR_ROOT_KEY,
        ),
        "seo": NamespacePolicy(
            write_mode=WriteMode.ATOMIC_REPLACE,
            dir_mode=DEFAULT_DIR_MODE,
            file_mode=DEFAULT_FILE_MODE,
            encrypt=False,
            base_root=VAR_ROOT_KEY,
        ),
        "secrets": NamespacePolicy(
            write_mode=WriteMode.ATOMIC_REPLACE,
            dir_mode=SECRETS_DIR_MODE,
            file_mode=SECRETS_FILE_MODE,
            encrypt=True,
            base_root=VAR_ROOT_KEY,
        ),
        "logs": NamespacePolicy(
            write_mode=WriteMode.APPEND,
            dir_mode=DEFAULT_DIR_MODE,
            file_mode=DEFAULT_FILE_MODE,
            encrypt=False,
            base_root=VAR_ROOT_KEY,
        ),
        "tmp": NamespacePolicy(
            write_mode=WriteMode.ATOMIC_REPLACE,
            dir_mode=DEFAULT_DIR_MODE,
            file_mode=DEFAULT_FILE_MODE,
            encrypt=False,
            base_root=VAR_ROOT_KEY,
        ),
        "uploads": NamespacePolicy(
            write_mode=WriteMode.ATOMIC_REPLACE,
            dir_mode=DEFAULT_DIR_MODE,
            file_mode=DEFAULT_FILE_MODE,
            encrypt=False,
            base_root=UPLOADS_ROOT_KEY,
            url_base=uploads_url_base,
        ),
    }


def validate_relative_path(namespace: str, relative_path: str) -> str:
    """Reject structurally unsafe relative paths; return the normalised value.

    Rejects absolute paths, NUL bytes, and any ``..`` segment. This is the
    portable half of the confinement guard (D3) shared by both impls; the disk
    impl additionally enforces realpath-within-namespace to stop symlink escape.
    """
    if "\x00" in relative_path:
        raise ValueError(
            f"Relative path for namespace '{namespace}' contains a NUL byte"
        )
    if os.path.isabs(relative_path):
        raise ValueError(
            f"Relative path '{relative_path}' for namespace '{namespace}' "
            "must not be absolute"
        )
    segments = relative_path.replace("\\", "/").split("/")
    if any(segment == ".." for segment in segments):
        raise ValueError(
            f"Relative path '{relative_path}' for namespace '{namespace}' "
            "must not contain '..' segments"
        )
    return relative_path
