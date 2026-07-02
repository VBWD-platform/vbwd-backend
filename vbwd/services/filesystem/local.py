"""On-disk implementation of the unified FilesystemManager (Sprint 58.0).

Owns two managed roots — ``${VBWD_VAR_DIR:-/app/var}`` and
``${UPLOADS_BASE_PATH:-/app/uploads}`` — and a registry of namespaces, each
with its :class:`NamespacePolicy`. Every operation flows through a single
``_resolve`` that confines ``(namespace, relative_path)`` to the namespace
subtree using ``realpath`` (defeating ``..`` and symlink escape), then applies
the namespace's write mode (D2), permissions, and optional encryption (D4).

This is intentionally a ~one-service absorber of the six existing file-access
sites; it is not a virtual filesystem (no pluggable S3 backend, no rotation —
that is Sprint 58.5).
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Optional

from vbwd.utils.crypto import get_default_cipher

from ._common import (
    VAR_ROOT_KEY,
    build_default_namespaces,
    build_default_plugin_policy,
    validate_namespace_segment,
    validate_relative_path,
)
from ._locking import exclusive_lock, shared_lock
from .ports import NamespacePolicy, PluginFilespace, WriteMode

DEFAULT_VAR_ROOT = "/app/var"
DEFAULT_UPLOADS_ROOT = "/app/uploads"
DEFAULT_UPLOADS_URL = "/uploads"

# The ``uploads`` namespace IS the uploads root (legacy on-disk layout
# ``<UPLOADS_BASE_PATH>/<relative_path>``), NOT ``<root>/uploads/<relative_path>``.
# Pin it so the namespace directory is the root itself — otherwise every already
# served URL and every existing file would gain a spurious ``uploads/`` segment
# (Sprint 58.3, D6).
UPLOADS_NAMESPACE = "uploads"


def build_uploads_pinned_manager() -> "LocalFilesystemManager":
    """Construct the production manager with the ``uploads`` namespace pinned to
    the uploads root, so blobs land at ``<UPLOADS_BASE_PATH>/<relative_path>``
    (byte-for-byte the legacy ``LocalFileStorage`` layout). The var/uploads
    roots and the uploads URL base come from the environment, exactly as before.
    """
    uploads_root = os.path.realpath(
        os.environ.get("UPLOADS_BASE_PATH", DEFAULT_UPLOADS_ROOT)
    )
    return LocalFilesystemManager(
        namespace_roots={UPLOADS_NAMESPACE: uploads_root},
    )


class LocalFilesystemManager:
    """Disk-backed :class:`IFilesystemManager`."""

    def __init__(
        self,
        namespaces: Optional[Dict[str, NamespacePolicy]] = None,
        var_root: Optional[str] = None,
        uploads_root: Optional[str] = None,
        uploads_url_base: Optional[str] = None,
        namespace_roots: Optional[Dict[str, str]] = None,
    ) -> None:
        var_root_path = (
            var_root if var_root else os.environ.get("VBWD_VAR_DIR", DEFAULT_VAR_ROOT)
        )
        uploads_root_path = (
            uploads_root
            if uploads_root
            else os.environ.get("UPLOADS_BASE_PATH", DEFAULT_UPLOADS_ROOT)
        )
        self._var_root = os.path.realpath(var_root_path)
        self._uploads_root = os.path.realpath(uploads_root_path)
        resolved_uploads_url = (
            uploads_url_base
            if uploads_url_base
            else os.environ.get("UPLOADS_BASE_URL", DEFAULT_UPLOADS_URL)
        )
        self._namespaces = namespaces or build_default_namespaces(resolved_uploads_url)
        # Optional per-namespace root override (D8 back-compat): pins a namespace
        # directly to an absolute directory instead of ``<base_root>/<namespace>``.
        # Used so an env-var-configured manifest path (e.g. a deployment that
        # mounts ``plugins.json`` outside the canonical ``var/plugins/`` dir) is
        # still served through the ``plugins`` namespace and its policy/locking.
        self._namespace_roots = {
            namespace: os.path.realpath(root)
            for namespace, root in (namespace_roots or {}).items()
        }
        # The single policy any non-reserved (plugin-owned) namespace resolves
        # to. Built once; core never enumerates plugin ids.
        self._plugin_policy = build_default_plugin_policy()

    # ------------------------------------------------------------------
    # Resolution + confinement (D3)
    # ------------------------------------------------------------------

    def _policy(self, namespace: str) -> NamespacePolicy:
        reserved = self._namespaces.get(namespace)
        if reserved is not None:
            return reserved
        # Any other namespace is a generic plugin-owned filespace rooted at
        # var/<namespace>/. The namespace string alone must be safe; the root is
        # derived from it, so core holds no list of plugin ids.
        validate_namespace_segment(namespace)
        return self._plugin_policy

    def for_plugin(self, plugin_id: str) -> PluginFilespace:
        validate_namespace_segment(plugin_id)
        if plugin_id in self._namespaces:
            raise ValueError(
                f"Plugin id '{plugin_id}' collides with a reserved core "
                "namespace and cannot be claimed as a plugin filespace"
            )
        return PluginFilespace(self, plugin_id)

    def _namespace_root(self, policy: NamespacePolicy, namespace: str) -> str:
        override = self._namespace_roots.get(namespace)
        if override is not None:
            return override
        root = (
            self._var_root if policy.base_root == VAR_ROOT_KEY else self._uploads_root
        )
        return os.path.join(root, namespace)

    def _resolve(self, namespace: str, relative_path: str) -> str:
        """Return the confined absolute path; raise on any escape attempt."""
        policy = self._policy(namespace)
        validate_relative_path(namespace, relative_path)

        namespace_root = self._namespace_root(policy, namespace)
        confined_root = os.path.realpath(namespace_root)
        candidate = os.path.realpath(os.path.join(namespace_root, relative_path))

        if candidate != confined_root and not candidate.startswith(
            confined_root + os.sep
        ):
            raise ValueError(
                f"Resolved path for namespace '{namespace}' escapes its root: "
                f"'{relative_path}'"
            )
        return candidate

    def resolve(self, namespace: str, relative_path: str) -> str:
        return self._resolve(namespace, relative_path)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def read_bytes(self, namespace: str, relative_path: str) -> bytes:
        policy = self._policy(namespace)
        target = self._resolve(namespace, relative_path)
        if policy.write_mode is WriteMode.INPLACE_LOCKED:
            with open(target, "rb") as handle:
                with shared_lock(handle):
                    raw = handle.read()
        else:
            with open(target, "rb") as handle:
                raw = handle.read()
        if policy.encrypt:
            return self._decrypt(raw)
        return raw

    def read_text(self, namespace: str, relative_path: str) -> str:
        return self.read_bytes(namespace, relative_path).decode("utf-8")

    def read_json(self, namespace: str, relative_path: str, default: Any = None) -> Any:
        try:
            raw = self.read_text(namespace, relative_path)
        except FileNotFoundError:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def write_text(self, namespace: str, relative_path: str, text: str) -> str:
        return self.write_bytes(namespace, relative_path, text.encode("utf-8"))

    def write_bytes(self, namespace: str, relative_path: str, data: bytes) -> str:
        policy = self._policy(namespace)
        target = self._resolve(namespace, relative_path)
        self._ensure_parent(target, policy)
        payload = self._encrypt(data) if policy.encrypt else data

        if policy.write_mode is WriteMode.ATOMIC_REPLACE:
            self._write_atomic(target, payload, policy)
        elif policy.write_mode is WriteMode.INPLACE_LOCKED:
            self._write_inplace_locked(target, payload, policy)
        elif policy.write_mode is WriteMode.APPEND:
            self._append_bytes(target, payload, policy)
        else:  # pragma: no cover - exhaustive guard
            raise ValueError(f"Unsupported write mode: {policy.write_mode}")
        return relative_path

    def write_json(self, namespace: str, relative_path: str, obj: Any) -> str:
        serialised = json.dumps(obj, ensure_ascii=False, indent=2)
        return self.write_text(namespace, relative_path, serialised)

    def append_text(self, namespace: str, relative_path: str, text: str) -> None:
        policy = self._policy(namespace)
        target = self._resolve(namespace, relative_path)
        self._ensure_parent(target, policy)
        self._append_bytes(target, text.encode("utf-8"), policy)

    def append_with_rotation(
        self,
        namespace: str,
        relative_path: str,
        text: str,
        max_bytes: int,
        backups: int,
    ) -> None:
        policy = self._policy(namespace)
        target = self._resolve(namespace, relative_path)
        self._ensure_parent(target, policy)
        payload = text.encode("utf-8")

        # A dedicated sidecar lock file gives a stable inode for the
        # check-rotate-append critical section: the active data file may be
        # renamed away during a roll, so locking it directly would let a
        # concurrent worker double-rotate. The sidecar is never rotated.
        lock_path = f"{target}.lock"
        lock_descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT, policy.file_mode)
        with os.fdopen(lock_descriptor, "wb") as lock_handle:
            with exclusive_lock(lock_handle):
                if self._exceeds(target, max_bytes, len(payload)):
                    self._rotate(target, backups)
                self._append_locked_target(target, payload, policy)

    @staticmethod
    def _exceeds(target: str, max_bytes: int, incoming: int) -> bool:
        if max_bytes <= 0:
            return False
        try:
            current = os.path.getsize(target)
        except OSError:
            return False
        return current > 0 and current + incoming > max_bytes

    def _rotate(self, target: str, backups: int) -> None:
        """Roll ``target`` -> ``target.1`` -> … -> ``target.<backups>``.

        The oldest segment is dropped; ``target`` is left absent so the next
        append starts a fresh segment.
        """
        if backups <= 0:
            # No history kept: just truncate by removing the active file.
            if os.path.exists(target):
                os.remove(target)
            return
        oldest = f"{target}.{backups}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for index in range(backups - 1, 0, -1):
            source = f"{target}.{index}"
            destination = f"{target}.{index + 1}"
            if os.path.exists(source):
                os.replace(source, destination)
        if os.path.exists(target):
            os.replace(target, f"{target}.1")

    def _append_locked_target(
        self, target: str, payload: bytes, policy: NamespacePolicy
    ) -> None:
        """Append to ``target`` without taking the per-file append lock.

        Used inside ``append_with_rotation`` where the sidecar lock already
        serialises writers, so the inner append must not re-lock.
        """
        file_descriptor = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, policy.file_mode
        )
        with os.fdopen(file_descriptor, "ab") as handle:
            handle.write(payload)
            handle.flush()

    # ------------------------------------------------------------------
    # Write-mode primitives
    # ------------------------------------------------------------------

    def _write_atomic(
        self, target: str, payload: bytes, policy: NamespacePolicy
    ) -> None:
        directory = os.path.dirname(target)
        file_descriptor, temp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(file_descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
        except OSError:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
        os.chmod(target, policy.file_mode)

    def _write_inplace_locked(
        self, target: str, payload: bytes, policy: NamespacePolicy
    ) -> None:
        # Open create-or-update so the inode is preserved across writes (the
        # bind-mount contract: never rename a bind-mounted single file).
        file_descriptor = os.open(target, os.O_RDWR | os.O_CREAT, policy.file_mode)
        with os.fdopen(file_descriptor, "r+b") as handle:
            with exclusive_lock(handle):
                handle.seek(0)
                handle.truncate(0)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        os.chmod(target, policy.file_mode)

    def _append_bytes(
        self, target: str, payload: bytes, policy: NamespacePolicy
    ) -> None:
        file_descriptor = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, policy.file_mode
        )
        with os.fdopen(file_descriptor, "ab") as handle:
            with exclusive_lock(handle):
                handle.write(payload)
                handle.flush()

    # ------------------------------------------------------------------
    # Misc ops
    # ------------------------------------------------------------------

    def delete(self, namespace: str, relative_path: str) -> None:
        target = self._resolve(namespace, relative_path)
        if os.path.exists(target):
            os.remove(target)

    def exists(self, namespace: str, relative_path: str) -> bool:
        target = self._resolve(namespace, relative_path)
        return os.path.exists(target)

    def listdir(self, namespace: str, relative_path: str = "") -> list[str]:
        target = self._resolve(namespace, relative_path)
        if not os.path.isdir(target):
            return []
        return os.listdir(target)

    def url_for(self, namespace: str, relative_path: str) -> str:
        policy = self._policy(namespace)
        validate_relative_path(namespace, relative_path)
        if policy.url_base is None:
            raise ValueError(f"Namespace '{namespace}' is not served over HTTP")
        return f"{policy.url_base.rstrip('/')}/{relative_path.lstrip('/')}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_parent(self, target: str, policy: NamespacePolicy) -> None:
        os.makedirs(os.path.dirname(target), mode=policy.dir_mode, exist_ok=True)

    @staticmethod
    def _encrypt(data: bytes) -> bytes:
        cipher = get_default_cipher()
        return cipher.encrypt(data.decode("utf-8")).encode("ascii")

    @staticmethod
    def _decrypt(raw: bytes) -> bytes:
        cipher = get_default_cipher()
        return cipher.decrypt(raw.decode("ascii")).encode("utf-8")
