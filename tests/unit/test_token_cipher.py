"""S05 — TokenCipher + EncryptedString contract tests."""
import os

import pytest
from cryptography.fernet import Fernet

from vbwd.utils.crypto import (
    EncryptedString,
    TokenCipher,
    get_default_cipher,
    reset_default_cipher_cache,
)


@pytest.fixture(autouse=True)
def _isolate_cipher_cache():
    """Each test starts with a clean cipher cache."""
    reset_default_cipher_cache()
    yield
    reset_default_cipher_cache()


def test_round_trip_preserves_plaintext():
    cipher = TokenCipher(Fernet.generate_key())
    ciphertext = cipher.encrypt("ghp_secret_token_value")
    assert ciphertext != "ghp_secret_token_value"
    assert cipher.decrypt(ciphertext) == "ghp_secret_token_value"


def test_decrypt_with_wrong_key_raises():
    from cryptography.fernet import InvalidToken

    cipher_a = TokenCipher(Fernet.generate_key())
    cipher_b = TokenCipher(Fernet.generate_key())
    ciphertext = cipher_a.encrypt("payload")
    with pytest.raises(InvalidToken):
        cipher_b.decrypt(ciphertext)


def test_default_cipher_uses_env_var_when_present(monkeypatch):
    explicit_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("VBWD_TOKEN_ENCRYPTION_KEY", explicit_key)
    cipher = get_default_cipher()
    # encrypt with default cipher, verify a peer using the same explicit
    # key can decrypt — proves the env var was honoured.
    peer = TokenCipher(explicit_key.encode("ascii"))
    ciphertext = cipher.encrypt("hello")
    assert peer.decrypt(ciphertext) == "hello"


def test_default_cipher_falls_back_to_flask_secret(monkeypatch):
    monkeypatch.delenv("VBWD_TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-flask-secret")
    cipher_one = get_default_cipher()
    # cache invalidates correctly if the seed env changes.
    reset_default_cipher_cache()
    cipher_two = get_default_cipher()
    payload = "deploy-token-abc"
    assert cipher_two.decrypt(cipher_one.encrypt(payload)) == payload


def test_default_cipher_works_in_pristine_environment(monkeypatch):
    """Last-resort fallback so unit tests never fail to construct a cipher."""
    monkeypatch.delenv("VBWD_TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    cipher = get_default_cipher()
    assert cipher.decrypt(cipher.encrypt("payload")) == "payload"


def test_encrypted_string_round_trip_through_orm(monkeypatch):
    """The ``EncryptedString`` TypeDecorator stores ciphertext, returns plaintext."""
    monkeypatch.delenv("VBWD_TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("FLASK_SECRET_KEY", "deterministic-test-seed")

    encrypted_column = EncryptedString()
    # Simulate the ORM bind+result cycle without a real DB.
    plaintext = "ghp_super_secret"
    on_disk = encrypted_column.process_bind_param(plaintext, dialect=None)
    assert on_disk != plaintext, "ciphertext must differ from plaintext"
    decoded = encrypted_column.process_result_value(on_disk, dialect=None)
    assert decoded == plaintext


def test_encrypted_string_none_round_trips_as_none():
    """Nullable columns keep working without a special case at the call site."""
    encrypted_column = EncryptedString()
    assert encrypted_column.process_bind_param(None, dialect=None) is None
    assert encrypted_column.process_result_value(None, dialect=None) is None


def test_encrypted_string_passes_legacy_plaintext_through(monkeypatch, caplog):
    """If a legacy plaintext row exists, return it as-is (log a warning) so
    the operator rotation script can re-encrypt without data loss."""
    monkeypatch.setenv("FLASK_SECRET_KEY", "deterministic")
    encrypted_column = EncryptedString()
    with caplog.at_level("WARNING"):
        result = encrypted_column.process_result_value(
            "plaintext-leftover", dialect=None
        )
    assert result == "plaintext-leftover"
    assert any("legacy plaintext" in record.message for record in caplog.records)


def test_no_todo_encrypt_in_ghrm():
    """The two ``# TODO: encrypt`` markers in the GHRM service must be gone."""
    here = os.path.dirname(os.path.abspath(__file__))
    backend = os.path.dirname(os.path.dirname(here))
    service_path = os.path.join(
        backend,
        "plugins",
        "ghrm",
        "src",
        "services",
        "github_access_service.py",
    )
    with open(service_path) as handle:
        source = handle.read()
    import re

    matches = re.findall(r"TODO.*encrypt", source, re.IGNORECASE)
    assert not matches, (
        f"plugins/ghrm/src/services/github_access_service.py still contains "
        f"{len(matches)} TODO(s) about encryption: {matches!r}. S05 must "
        "remove them."
    )
