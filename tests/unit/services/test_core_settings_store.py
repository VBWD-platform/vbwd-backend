"""S57 — unit tests for the file-backed core settings store.

TDD RED: written before ``vbwd/services/core_settings_store.py`` exists.

Covers: defaults when the file is absent, round-tripping a written file,
defaults merging over a partial file (forward-compat for new keys), known-key
whitelisting on update, atomic persistence visible to a *fresh* read
(persistence-across-"restart" proof), and corrupt JSON degrading to defaults
without raising.
"""
import json
import os

import pytest

from vbwd.services.core_settings_store import (
    DEFAULT_CORE_SETTINGS,
    get_core_settings,
    update_core_settings,
)


@pytest.fixture(autouse=True)
def isolated_var_dir(tmp_path, monkeypatch):
    """Point the store at a throwaway ``VBWD_VAR_DIR`` for each test."""
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    return tmp_path


def _settings_file(var_dir) -> str:
    return os.path.join(str(var_dir), "core", "vbwd_settings.json")


def test_defaults_when_file_absent():
    settings = get_core_settings()
    assert settings == DEFAULT_CORE_SETTINGS
    # A read must never create the file (creation happens on first write).
    assert not os.path.exists(_settings_file(os.environ["VBWD_VAR_DIR"]))


def test_round_trips_a_written_file(isolated_var_dir):
    path = _settings_file(isolated_var_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    stored = {
        **DEFAULT_CORE_SETTINGS,
        "provider_name": "Acme GmbH",
        "bank_iban": "DE89370400440532013000",
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(stored, handle)

    settings = get_core_settings()
    assert settings["provider_name"] == "Acme GmbH"
    assert settings["bank_iban"] == "DE89370400440532013000"


def test_defaults_merge_over_partial_file(isolated_var_dir):
    """A file missing newer keys still yields the full schema (defaults fill)."""
    path = _settings_file(isolated_var_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"provider_name": "Partial Co"}, handle)

    settings = get_core_settings()
    assert settings["provider_name"] == "Partial Co"
    # Every default key is present even though the file only had one.
    assert set(settings) == set(DEFAULT_CORE_SETTINGS)
    assert settings["bank_iban"] == DEFAULT_CORE_SETTINGS["bank_iban"]


def test_update_whitelists_known_keys_and_persists():
    merged = update_core_settings(
        {"provider_name": "Persisted Inc", "unknown_key": "ignored"}
    )
    assert merged["provider_name"] == "Persisted Inc"
    assert "unknown_key" not in merged

    # Persistence-across-"restart" proof: a brand new read sees the value.
    reread = get_core_settings()
    assert reread["provider_name"] == "Persisted Inc"
    assert "unknown_key" not in reread


def test_update_creates_file_and_dir(isolated_var_dir):
    update_core_settings({"contact_email": "ops@example.com"})
    assert os.path.exists(_settings_file(isolated_var_dir))


def test_update_preserves_previously_stored_values():
    update_core_settings({"provider_name": "First"})
    update_core_settings({"contact_email": "second@example.com"})

    settings = get_core_settings()
    assert settings["provider_name"] == "First"
    assert settings["contact_email"] == "second@example.com"


def test_corrupt_json_falls_back_to_defaults(isolated_var_dir):
    path = _settings_file(isolated_var_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{ this is not valid json")

    settings = get_core_settings()
    assert settings == DEFAULT_CORE_SETTINGS  # no raise
