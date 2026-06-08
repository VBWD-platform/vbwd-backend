"""Sprint 58.3 — ``ManagerBackedFileStorage`` parity tests.

The adapter implements the legacy ``IFileStorage`` contract over the unified
``FilesystemManager``'s ``uploads`` namespace. It must be behaviour-identical to
the now-deleted ``LocalFileStorage``: **same on-disk path, same served URL, same
bytes** — while inheriting the manager's realpath-within-namespace confinement.

These tests are written RED first (the adapter does not yet exist) and pin the
path/URL mapping BEFORE any consumer is migrated, so the double-``uploads/``
segment trap (the ``uploads`` namespace defaulting to
``<uploads_root>/uploads/...``) is caught here, not in a broken served URL.
"""
import os

import pytest

from vbwd.interfaces.file_storage import IFileStorage, ManagerBackedFileStorage
from vbwd.services.filesystem.local import LocalFilesystemManager
from vbwd.services.filesystem.memory import InMemoryFilesystemManager

UPLOADS_BASE_URL = "/uploads"


def _disk_storage(uploads_root: str) -> ManagerBackedFileStorage:
    manager = LocalFilesystemManager(
        uploads_root=uploads_root,
        uploads_url_base=UPLOADS_BASE_URL,
        namespace_roots={"uploads": uploads_root},
    )
    return ManagerBackedFileStorage(manager)


def test_adapter_is_an_ifilestorage(tmp_path):
    assert isinstance(_disk_storage(str(tmp_path)), IFileStorage)


def test_save_lands_at_uploads_root_without_double_segment(tmp_path):
    """``save`` must land at ``<uploads_root>/cms/images/x.png`` — exactly where
    the legacy ``LocalFileStorage`` wrote it, NOT under an extra ``uploads/``."""
    uploads_root = str(tmp_path)
    storage = _disk_storage(uploads_root)

    relative_path = "cms/images/x.png"
    returned = storage.save(b"data", relative_path)

    expected_on_disk = os.path.join(uploads_root, "cms", "images", "x.png")
    assert returned == relative_path
    assert os.path.isfile(expected_on_disk)
    # No double-segment directory was created.
    assert not os.path.exists(os.path.join(uploads_root, "uploads"))


def test_get_url_matches_legacy_base_url(tmp_path):
    storage = _disk_storage(str(tmp_path))
    assert storage.get_url("cms/images/x.png") == "/uploads/cms/images/x.png"


def test_meinchat_nested_path_parity(tmp_path):
    uploads_root = str(tmp_path)
    storage = _disk_storage(uploads_root)
    relative_path = "meinchat/attachments/abc123/photo.webp"

    storage.save(b"webp-bytes", relative_path)

    expected_on_disk = os.path.join(
        uploads_root, "meinchat", "attachments", "abc123", "photo.webp"
    )
    assert os.path.isfile(expected_on_disk)
    assert (
        storage.get_url(relative_path)
        == "/uploads/meinchat/attachments/abc123/photo.webp"
    )


def test_round_trip_bytes_identical(tmp_path):
    storage = _disk_storage(str(tmp_path))
    payload = b"\x00\x01binary\xfftail"
    relative_path = "cms/imports/job.zip"

    storage.save(payload, relative_path)
    assert storage.exists(relative_path) is True
    assert storage.read(relative_path) == payload

    storage.delete(relative_path)
    assert storage.exists(relative_path) is False


def test_traversal_relative_path_is_rejected(tmp_path):
    storage = _disk_storage(str(tmp_path))
    with pytest.raises(ValueError):
        storage.save(b"x", "../escape.png")


def test_absolute_relative_path_is_rejected(tmp_path):
    storage = _disk_storage(str(tmp_path))
    with pytest.raises(ValueError):
        storage.save(b"x", "/etc/passwd")


def test_in_memory_manager_backing_round_trips():
    """The adapter also works over the in-memory manager (the preferred test
    double), so call-sites can be unit-tested without disk."""
    manager = InMemoryFilesystemManager(uploads_base_url=UPLOADS_BASE_URL)
    storage = ManagerBackedFileStorage(manager)

    storage.save(b"payload", "cms/images/y.png")
    assert storage.exists("cms/images/y.png")
    assert storage.read("cms/images/y.png") == b"payload"
    assert storage.get_url("cms/images/y.png") == "/uploads/cms/images/y.png"
