"""Sprint 58.0 — acceptance tests for the unified FilesystemManager.

These tests are the contract. They exercise BOTH the on-disk
``LocalFilesystemManager`` (rooted at a ``tmp_path``) and the
``InMemoryFilesystemManager`` test double, asserting the same confinement and
round-trip semantics from each (Liskov: the test double obeys the production
contract).

The covered behaviours mirror the sprint's TDD plan:
  * path confinement (``..`` / absolute / NUL / symlink-escape all raise;
    legal nested paths pass).
  * ``ATOMIC_REPLACE`` crash-safety (a failed write leaves the old file intact
    and no temp file behind) + file-mode application.
  * ``INPLACE_LOCKED`` preserves the target inode across writes (the bind-mount
    contract) and never yields a torn read under concurrent writer/reader.
  * ``APPEND`` concurrent appenders never interleave a line.
  * JSON round-trip + corrupt/missing -> default.
  * ``secrets`` namespace: 0600 mode + on-disk ciphertext when encrypt=True.
  * ``url_for`` maps an uploads rel-path to the public URL; non-url ns raises.
  * DI: ``container.filesystem_manager()`` returns a working manager.
"""
import json
import os
import threading

import pytest

from vbwd.services.filesystem import (
    InMemoryFilesystemManager,
    LocalFilesystemManager,
    NamespacePolicy,
    WriteMode,
)


@pytest.fixture
def local_manager(tmp_path, monkeypatch):
    """A LocalFilesystemManager rooted entirely under a throwaway tmp dir."""
    var_root = tmp_path / "var"
    uploads_root = tmp_path / "uploads"
    var_root.mkdir()
    uploads_root.mkdir()
    monkeypatch.setenv("VBWD_VAR_DIR", str(var_root))
    monkeypatch.setenv("UPLOADS_BASE_PATH", str(uploads_root))
    monkeypatch.setenv("UPLOADS_BASE_URL", "/uploads")
    return LocalFilesystemManager()


@pytest.fixture
def memory_manager():
    """The in-memory test double with the same default namespaces."""
    return InMemoryFilesystemManager(uploads_base_url="/uploads")


# Managers that must both honour confinement + JSON round-trip semantics.
@pytest.fixture(params=["local", "memory"])
def either_manager(request, local_manager, memory_manager):
    return local_manager if request.param == "local" else memory_manager


# ----------------------------------------------------------------------------
# Confinement (D3) — applies to both impls
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_rel",
    [
        "../escape.txt",
        "nested/../../escape.txt",
        "/absolute/path.txt",
        "with\x00nul.txt",
    ],
)
def test_confinement_rejects_illegal_relative_paths(either_manager, bad_rel):
    with pytest.raises(ValueError):
        either_manager.write_text("core", bad_rel, "x")


def test_confinement_rejects_unknown_namespace(either_manager):
    with pytest.raises(ValueError):
        either_manager.write_text("does-not-exist", "a.txt", "x")


def test_confinement_allows_legal_nested_path(either_manager):
    either_manager.write_text("core", "a/b/c.txt", "hello")
    assert either_manager.read_text("core", "a/b/c.txt") == "hello"


def test_confinement_rejects_symlink_escape(local_manager, tmp_path):
    """A symlink inside the namespace pointing outside must not be writable."""
    var_root = tmp_path / "var"
    core_dir = var_root / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    # core/link -> ../../outside  (resolves outside the namespace)
    os.symlink(str(outside), str(core_dir / "link"))

    with pytest.raises(ValueError):
        local_manager.write_text("core", "link/pwned.txt", "x")
    with pytest.raises(ValueError):
        local_manager.read_text("core", "link/pwned.txt")


# ----------------------------------------------------------------------------
# ATOMIC_REPLACE (D2)
# ----------------------------------------------------------------------------


def test_atomic_replace_failure_leaves_old_content_and_no_temp(
    local_manager, tmp_path, monkeypatch
):
    local_manager.write_text("core", "settings.json", "original")
    core_dir = tmp_path / "var" / "core"

    def boom(*args, **kwargs):
        raise OSError("simulated disk failure before replace")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        local_manager.write_text("core", "settings.json", "new-content")

    # Old content intact.
    assert local_manager.read_text("core", "settings.json") == "original"
    # No leftover temp files in the directory.
    leftovers = [name for name in os.listdir(core_dir) if name != "settings.json"]
    assert leftovers == []


def test_atomic_replace_applies_file_mode(local_manager, tmp_path):
    local_manager.write_text("core", "settings.json", "data")
    target = tmp_path / "var" / "core" / "settings.json"
    assert (target.stat().st_mode & 0o777) == 0o644


# ----------------------------------------------------------------------------
# INPLACE_LOCKED (D2) — bind-mount contract
# ----------------------------------------------------------------------------


def test_inplace_locked_preserves_inode_across_writes(local_manager, tmp_path):
    local_manager.write_text("plugins", "backend-plugins.json", '{"a": 1}')
    target = tmp_path / "var" / "plugins" / "backend-plugins.json"
    inode_before = target.stat().st_ino

    local_manager.write_text("plugins", "backend-plugins.json", '{"a": 2}')
    inode_after = target.stat().st_ino

    assert inode_before == inode_after  # no rename happened
    assert local_manager.read_text("plugins", "backend-plugins.json") == '{"a": 2}'


def test_inplace_locked_concurrent_writer_reader_no_torn_read(local_manager):
    """A reader under a shared lock never observes a partial manifest."""
    payload_a = json.dumps({"value": "A" * 2000})
    payload_b = json.dumps({"value": "B" * 2000})
    local_manager.write_text("plugins", "race.json", payload_a)

    stop = threading.Event()
    torn = []

    def writer():
        toggle = True
        while not stop.is_set():
            local_manager.write_text(
                "plugins", "race.json", payload_a if toggle else payload_b
            )
            toggle = not toggle

    def reader():
        while not stop.is_set():
            content = local_manager.read_text("plugins", "race.json")
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                torn.append(content)
                return
            if parsed["value"] not in ("A" * 2000, "B" * 2000):
                torn.append(content)
                return

    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)
    writer_thread.start()
    reader_thread.start()
    reader_thread.join(timeout=2.0)
    stop.set()
    writer_thread.join(timeout=2.0)
    reader_thread.join(timeout=2.0)

    assert torn == []


# ----------------------------------------------------------------------------
# APPEND (D2)
# ----------------------------------------------------------------------------


def test_append_concurrent_appenders_do_not_interleave_lines(local_manager):
    line_a = "A" * 500 + "\n"
    line_b = "B" * 500 + "\n"

    def appender(line, count):
        for _ in range(count):
            local_manager.append_text("logs", "core/events.log", line)

    thread_a = threading.Thread(target=appender, args=(line_a, 50))
    thread_b = threading.Thread(target=appender, args=(line_b, 50))
    thread_a.start()
    thread_b.start()
    thread_a.join()
    thread_b.join()

    content = local_manager.read_text("logs", "core/events.log")
    lines = content.splitlines(keepends=True)
    assert len(lines) == 100
    for line in lines:
        assert line in (line_a, line_b)  # no mid-line interleave


# ----------------------------------------------------------------------------
# JSON helpers
# ----------------------------------------------------------------------------


def test_json_round_trip(either_manager):
    obj = {"name": "vbwd", "count": 3, "nested": {"on": True}}
    either_manager.write_json("core", "config.json", obj)
    assert either_manager.read_json("core", "config.json") == obj


def test_read_json_missing_returns_default(either_manager):
    sentinel = {"fallback": True}
    assert either_manager.read_json("core", "absent.json", default=sentinel) is sentinel


def test_read_json_corrupt_returns_default(either_manager):
    either_manager.write_text("core", "broken.json", "{ this is not json ")
    sentinel = ["default"]
    assert either_manager.read_json("core", "broken.json", default=sentinel) is sentinel


# ----------------------------------------------------------------------------
# Secrets namespace (D4)
# ----------------------------------------------------------------------------


def test_secrets_file_written_with_0600_mode(local_manager, tmp_path):
    local_manager.write_text("secrets", "github-app.pem", "PRIVATE-KEY")
    target = tmp_path / "var" / "secrets" / "github-app.pem"
    assert (target.stat().st_mode & 0o777) == 0o600


def test_secrets_on_disk_bytes_are_ciphertext_and_read_decrypts(
    local_manager, tmp_path
):
    plaintext = "super-secret-token-value"
    local_manager.write_text("secrets", "token.txt", plaintext)

    raw_on_disk = (tmp_path / "var" / "secrets" / "token.txt").read_bytes()
    assert plaintext.encode("utf-8") not in raw_on_disk  # encrypted at rest

    assert local_manager.read_text("secrets", "token.txt") == plaintext


# ----------------------------------------------------------------------------
# url_for / resolve
# ----------------------------------------------------------------------------


def test_url_for_uploads_uses_configured_base_url(either_manager):
    assert either_manager.url_for("uploads", "cms/images/x.png") == (
        "/uploads/cms/images/x.png"
    )


def test_url_for_non_url_namespace_raises(either_manager):
    with pytest.raises(ValueError):
        either_manager.url_for("core", "settings.json")


def test_resolve_returns_confined_path_without_requiring_existence(
    local_manager, tmp_path
):
    resolved = local_manager.resolve("secrets", "github-app.pem")
    expected = str(tmp_path / "var" / "secrets" / "github-app.pem")
    assert resolved == os.path.realpath(expected)
    assert not os.path.exists(resolved)  # not created by resolve


def test_resolve_confines_path(local_manager):
    with pytest.raises(ValueError):
        local_manager.resolve("secrets", "../escape.pem")


# ----------------------------------------------------------------------------
# exists / delete / listdir (cross-impl)
# ----------------------------------------------------------------------------


def test_exists_and_delete(either_manager):
    assert either_manager.exists("core", "x.txt") is False
    either_manager.write_text("core", "x.txt", "data")
    assert either_manager.exists("core", "x.txt") is True
    either_manager.delete("core", "x.txt")
    assert either_manager.exists("core", "x.txt") is False


def test_listdir_returns_entries(either_manager):
    either_manager.write_text("core", "dir/one.txt", "1")
    either_manager.write_text("core", "dir/two.txt", "2")
    entries = sorted(either_manager.listdir("core", "dir"))
    assert entries == ["one.txt", "two.txt"]


def test_bytes_round_trip(either_manager):
    payload = b"\x00\x01\x02binary\xff"
    either_manager.write_bytes("uploads", "blob.bin", payload)
    assert either_manager.read_bytes("uploads", "blob.bin") == payload


# ----------------------------------------------------------------------------
# Namespace policy registry shape
# ----------------------------------------------------------------------------


def test_default_namespaces_present(local_manager):
    for namespace in ("core", "plugins", "seo", "secrets", "logs", "tmp", "uploads"):
        # resolve must succeed (path confinement happy path) for every default ns
        local_manager.resolve(namespace, "probe.txt")


def test_namespace_policy_is_a_value_object():
    policy = NamespacePolicy(
        write_mode=WriteMode.ATOMIC_REPLACE,
        dir_mode=0o755,
        file_mode=0o644,
        encrypt=False,
        base_root="var",
        url_base=None,
    )
    assert policy.write_mode is WriteMode.ATOMIC_REPLACE
    assert policy.file_mode == 0o644


# ----------------------------------------------------------------------------
# DI registration
# ----------------------------------------------------------------------------


def test_container_provides_filesystem_manager():
    from vbwd.container import Container

    container = Container()
    manager = container.filesystem_manager()
    assert isinstance(manager, LocalFilesystemManager)
    # singleton — same instance on second resolve
    assert container.filesystem_manager() is manager
