"""Advisory file locking helper (D7).

Wraps ``fcntl.flock`` so the INPLACE_LOCKED / APPEND write modes can coordinate
across the three bind-mounted containers (they share the host inode). On a
platform without ``fcntl`` (e.g. Windows dev boxes) the helper degrades to a
no-op so tests and single-process dev never hang.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import IO, Iterator

try:
    import fcntl

    _FLOCK_AVAILABLE = True
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]
    _FLOCK_AVAILABLE = False


@contextmanager
def exclusive_lock(handle: IO) -> Iterator[None]:
    """Hold an exclusive (writer) advisory lock for the block's duration."""
    if _FLOCK_AVAILABLE:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        if _FLOCK_AVAILABLE:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def shared_lock(handle: IO) -> Iterator[None]:
    """Hold a shared (reader) advisory lock for the block's duration."""
    if _FLOCK_AVAILABLE:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
    try:
        yield
    finally:
        if _FLOCK_AVAILABLE:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
