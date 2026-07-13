"""The soft instance fingerprint is stable per host+salt and varies by salt."""
from vbwd.security.licensing.instance_fingerprint import (
    compute_instance_fingerprint,
    database_host_from_url,
    load_or_create_salt,
    resolve_instance_fingerprint,
)


def test_same_host_and_salt_is_stable():
    first = compute_instance_fingerprint("db.internal", "salt-1")
    second = compute_instance_fingerprint("db.internal", "salt-1")
    assert first == second


def test_different_salt_differs():
    assert compute_instance_fingerprint(
        "db.internal", "salt-1"
    ) != compute_instance_fingerprint("db.internal", "salt-2")


def test_database_host_from_url():
    assert database_host_from_url("postgresql://user:pw@postgres:5432/vbwd") == (
        "postgres"
    )


def test_salt_is_persisted_and_reused(tmp_path):
    first = load_or_create_salt(str(tmp_path))
    second = load_or_create_salt(str(tmp_path))
    assert first == second
    assert (tmp_path / ".salt").exists()


def test_resolve_is_stable_across_calls(tmp_path):
    url = "postgresql://vbwd:vbwd@postgres:5432/vbwd"
    first = resolve_instance_fingerprint(url, str(tmp_path))
    second = resolve_instance_fingerprint(url, str(tmp_path))
    assert first == second
