"""In-memory implementation of the FilesystemManager (Sprint 58.0).

A dict-backed test double honouring the same port and confinement semantics as
:class:`LocalFilesystemManager`, so plugin/unit tests can swap it in without
touching disk (Liskov: same contract, including the relative-path guard and the
``url_for`` / unknown-namespace errors). It supersedes the two
``InMemoryFileStorage`` copies conceptually; the physical removal happens in
Sprint 58.3.

It does not encrypt at rest (there is no disk to protect) and treats every
write mode identically — the durability/locking semantics only matter on real
files, so the in-memory double keeps behaviour observable without simulating
them.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from ._common import (
    build_default_namespaces,
    build_default_plugin_policy,
    validate_namespace_segment,
    validate_relative_path,
)
from .ports import NamespacePolicy, PluginFilespace


class InMemoryFilesystemManager:
    """Dict-backed :class:`IFilesystemManager` for tests."""

    def __init__(
        self,
        namespaces: Optional[Dict[str, NamespacePolicy]] = None,
        uploads_base_url: str = "/uploads",
    ) -> None:
        self._namespaces = namespaces or build_default_namespaces(uploads_base_url)
        # The single policy any non-reserved (plugin-owned) namespace resolves
        # to; core never enumerates plugin ids.
        self._plugin_policy = build_default_plugin_policy()
        # keyed by (namespace, normalised relative path) -> bytes
        self._store: Dict[tuple[str, str], bytes] = {}

    # ------------------------------------------------------------------
    # Resolution + confinement (D3, portable half)
    # ------------------------------------------------------------------

    def _policy(self, namespace: str) -> NamespacePolicy:
        reserved = self._namespaces.get(namespace)
        if reserved is not None:
            return reserved
        # Any other namespace is a generic plugin-owned filespace; the string
        # alone must be safe (core never enumerates plugin ids).
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

    def _key(self, namespace: str, relative_path: str) -> tuple[str, str]:
        self._policy(namespace)
        validate_relative_path(namespace, relative_path)
        normalised = relative_path.replace("\\", "/").strip("/")
        return (namespace, normalised)

    def resolve(self, namespace: str, relative_path: str) -> str:
        self._policy(namespace)
        validate_relative_path(namespace, relative_path)
        return f"memory://{namespace}/{relative_path.lstrip('/')}"

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def read_bytes(self, namespace: str, relative_path: str) -> bytes:
        key = self._key(namespace, relative_path)
        if key not in self._store:
            raise FileNotFoundError(f"{namespace}/{relative_path}")
        return self._store[key]

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

    def write_bytes(self, namespace: str, relative_path: str, data: bytes) -> str:
        key = self._key(namespace, relative_path)
        self._store[key] = bytes(data)
        return relative_path

    def write_text(self, namespace: str, relative_path: str, text: str) -> str:
        return self.write_bytes(namespace, relative_path, text.encode("utf-8"))

    def write_json(self, namespace: str, relative_path: str, obj: Any) -> str:
        serialised = json.dumps(obj, ensure_ascii=False, indent=2)
        return self.write_text(namespace, relative_path, serialised)

    def append_text(self, namespace: str, relative_path: str, text: str) -> None:
        key = self._key(namespace, relative_path)
        existing = self._store.get(key, b"")
        self._store[key] = existing + text.encode("utf-8")

    def append_with_rotation(
        self,
        namespace: str,
        relative_path: str,
        text: str,
        max_bytes: int,
        backups: int,
    ) -> None:
        key = self._key(namespace, relative_path)
        payload = text.encode("utf-8")
        existing = self._store.get(key, b"")
        if max_bytes > 0 and existing and len(existing) + len(payload) > max_bytes:
            self._rotate(namespace, relative_path, backups)
            existing = b""
        self._store[key] = existing + payload

    def _rotate(self, namespace: str, relative_path: str, backups: int) -> None:
        normalised = relative_path.replace("\\", "/").strip("/")
        if backups <= 0:
            self._store.pop((namespace, normalised), None)
            return
        oldest = (namespace, f"{normalised}.{backups}")
        self._store.pop(oldest, None)
        for index in range(backups - 1, 0, -1):
            source = (namespace, f"{normalised}.{index}")
            destination = (namespace, f"{normalised}.{index + 1}")
            if source in self._store:
                self._store[destination] = self._store.pop(source)
        active = (namespace, normalised)
        if active in self._store:
            self._store[(namespace, f"{normalised}.1")] = self._store.pop(active)

    # ------------------------------------------------------------------
    # Misc ops
    # ------------------------------------------------------------------

    def delete(self, namespace: str, relative_path: str) -> None:
        self._store.pop(self._key(namespace, relative_path), None)

    def exists(self, namespace: str, relative_path: str) -> bool:
        return self._key(namespace, relative_path) in self._store

    def listdir(self, namespace: str, relative_path: str = "") -> list[str]:
        self._policy(namespace)
        validate_relative_path(namespace, relative_path)
        prefix = relative_path.replace("\\", "/").strip("/")
        prefix = f"{prefix}/" if prefix else ""
        entries: set[str] = set()
        for stored_namespace, stored_path in self._store:
            if stored_namespace != namespace:
                continue
            if not stored_path.startswith(prefix):
                continue
            remainder = stored_path[len(prefix) :]
            if not remainder:
                continue
            entries.add(remainder.split("/", 1)[0])
        return list(entries)

    def url_for(self, namespace: str, relative_path: str) -> str:
        policy = self._policy(namespace)
        validate_relative_path(namespace, relative_path)
        if policy.url_base is None:
            raise ValueError(f"Namespace '{namespace}' is not served over HTTP")
        return f"{policy.url_base.rstrip('/')}/{relative_path.lstrip('/')}"
