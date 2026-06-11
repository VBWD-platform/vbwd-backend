"""S52.0 — core ``api_key`` model unit tests.

The model is a generic auth-mechanism entity (no domain fields). ``to_dict``
must never leak the secret hash — only the display ``key_prefix``.
"""
from vbwd.models.api_key import ApiKey


def _build_key() -> ApiKey:
    api_key = ApiKey()
    api_key.label = "CI pipeline"
    api_key.key_hash = "a" * 64
    api_key.key_prefix = "vbwdk_ab12"
    api_key.scopes = ["cms:posts:create"]
    api_key.ip_whitelist = ["10.0.0.0/8"]
    api_key.is_active = True
    return api_key


def test_to_dict_exposes_prefix_not_hash():
    api_key = _build_key()

    data = api_key.to_dict()

    assert data["label"] == "CI pipeline"
    assert data["key_prefix"] == "vbwdk_ab12"
    assert data["scopes"] == ["cms:posts:create"]
    assert data["ip_whitelist"] == ["10.0.0.0/8"]
    assert data["is_active"] is True


def test_to_dict_never_leaks_key_hash():
    api_key = _build_key()

    data = api_key.to_dict()

    assert "key_hash" not in data
    assert ("a" * 64) not in data.values()


def test_to_dict_serialises_timestamps_as_isoformat():
    from datetime import datetime

    api_key = _build_key()
    api_key.last_used_at = datetime(2026, 6, 6, 12, 0, 0)

    data = api_key.to_dict()

    assert data["last_used_at"] == "2026-06-06T12:00:00"
