"""S52.1 — core ``ApiKeyService`` unit tests (no DB, MagicMock repo).

Security must-haves asserted here: plaintext returned once + never stored;
sha256 hashing; constant-time compare; IP whitelist (exact + CIDR); exact
scope membership (empty ⇒ deny); owner-guarded revoke.
"""
import hashlib
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.api_key import ApiKey
from vbwd.services.api_key_service import ApiKeyService


def _service():
    repo = MagicMock()
    repo.save.side_effect = lambda entity: entity
    return ApiKeyService(repository=repo), repo


def test_generate_returns_plaintext_once_with_prefix_and_persists_hash():
    service, repo = _service()
    user_id = uuid4()

    api_key, plaintext = service.generate(
        user_id=user_id, label="CI", scopes=["cms:posts:create"]
    )

    assert plaintext.startswith("vbwdk_")
    # The persisted hash is sha256(plaintext); plaintext itself is never stored.
    assert api_key.key_hash == hashlib.sha256(plaintext.encode()).hexdigest()
    assert api_key.key_hash != plaintext
    assert api_key.key_prefix.startswith("vbwdk_")
    assert plaintext.startswith(api_key.key_prefix)
    assert api_key.user_id == user_id
    assert api_key.scopes == ["cms:posts:create"]
    repo.save.assert_called_once()


def test_generate_records_creator_when_admin_acts():
    service, _ = _service()
    owner = uuid4()
    admin = uuid4()

    api_key, _ = service.generate(
        user_id=owner, label="k", scopes=[], created_by_user_id=admin
    )

    assert api_key.created_by_user_id == admin


def test_verify_returns_active_key_on_hash_match():
    service, repo = _service()
    plaintext = "vbwdk_secret"
    stored = ApiKey()
    stored.is_active = True
    stored.key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    repo.find_by_hash.return_value = stored

    assert service.verify(plaintext) is stored
    repo.find_by_hash.assert_called_once_with(
        hashlib.sha256(plaintext.encode()).hexdigest()
    )


def test_verify_rejects_inactive_key():
    service, repo = _service()
    stored = ApiKey()
    stored.is_active = False
    stored.key_hash = hashlib.sha256(b"vbwdk_x").hexdigest()
    repo.find_by_hash.return_value = stored

    assert service.verify("vbwdk_x") is None


def test_verify_rejects_unknown_or_blank():
    service, repo = _service()
    repo.find_by_hash.return_value = None
    assert service.verify("vbwdk_unknown") is None
    assert service.verify("") is None
    assert service.verify(None) is None


def test_is_ip_allowed_empty_whitelist_allows_any():
    service, _ = _service()
    key = ApiKey()
    key.ip_whitelist = []
    assert service.is_ip_allowed(key, "203.0.113.7") is True


def test_is_ip_allowed_exact_match():
    service, _ = _service()
    key = ApiKey()
    key.ip_whitelist = ["203.0.113.7"]
    assert service.is_ip_allowed(key, "203.0.113.7") is True
    assert service.is_ip_allowed(key, "203.0.113.8") is False


def test_is_ip_allowed_cidr_match():
    service, _ = _service()
    key = ApiKey()
    key.ip_whitelist = ["10.0.0.0/8"]
    assert service.is_ip_allowed(key, "10.1.2.3") is True
    assert service.is_ip_allowed(key, "192.168.1.1") is False


def test_is_ip_allowed_handles_unparseable_client_ip():
    service, _ = _service()
    key = ApiKey()
    key.ip_whitelist = ["10.0.0.0/8"]
    assert service.is_ip_allowed(key, "not-an-ip") is False


def test_has_scope_exact_membership():
    service, _ = _service()
    key = ApiKey()
    key.scopes = ["cms:posts:create"]
    assert service.has_scope(key, "cms:posts:create") is True
    assert service.has_scope(key, "cms:posts:delete") is False


def test_has_scope_empty_denies():
    service, _ = _service()
    key = ApiKey()
    key.scopes = []
    assert service.has_scope(key, "cms:posts:create") is False


def test_touch_stamps_last_used_and_saves():
    service, repo = _service()
    key = ApiKey()
    assert key.last_used_at is None

    service.touch(key)

    assert key.last_used_at is not None
    repo.save.assert_called_once_with(key)


def test_revoke_owner_guard_blocks_other_user():
    service, repo = _service()
    owner = uuid4()
    other = uuid4()
    key = ApiKey()
    key.user_id = owner
    repo.find_by_id.return_value = key

    with pytest.raises(PermissionError):
        service.revoke(uuid4(), owner_id=other)
    repo.revoke.assert_not_called()


def test_revoke_owner_guard_allows_owner():
    service, repo = _service()
    owner = uuid4()
    key = ApiKey()
    key.user_id = owner
    repo.find_by_id.return_value = key
    repo.revoke.return_value = True

    assert service.revoke(uuid4(), owner_id=owner) is True


def test_revoke_admin_no_owner_check():
    service, repo = _service()
    key = ApiKey()
    key.user_id = uuid4()
    repo.find_by_id.return_value = key
    repo.revoke.return_value = True

    assert service.revoke(uuid4()) is True
