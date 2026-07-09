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


def test_non_object_json_falls_back_to_defaults(isolated_var_dir):
    """A JSON file whose top level is not an object degrades to defaults."""
    path = _settings_file(isolated_var_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('["not", "an", "object"]')

    settings = get_core_settings()
    assert settings == DEFAULT_CORE_SETTINGS  # no raise


def test_site_name_defaults_to_empty_string():
    """White-label brand/site name defaults to an empty string."""
    assert "site_name" in DEFAULT_CORE_SETTINGS
    assert DEFAULT_CORE_SETTINGS["site_name"] == ""
    assert get_core_settings()["site_name"] == ""


def test_site_name_persists_across_read():
    """A saved site_name round-trips across a fresh read."""
    merged = update_core_settings({"site_name": "Acme"})
    assert merged["site_name"] == "Acme"

    reread = get_core_settings()
    assert reread["site_name"] == "Acme"


def test_prices_display_mode_defaults_to_brutto():
    """S72.4 D-global: the global netto/brutto toggle defaults to ``brutto``."""
    settings = get_core_settings()
    assert settings["prices_display_mode"] == "brutto"


def test_prices_display_mode_persists_netto():
    """S72.4: ``netto`` is a valid value and round-trips across a fresh read."""
    merged = update_core_settings({"prices_display_mode": "netto"})
    assert merged["prices_display_mode"] == "netto"

    reread = get_core_settings()
    assert reread["prices_display_mode"] == "netto"


def test_prices_display_mode_rejects_unknown_value(isolated_var_dir):
    """S72.4: an out-of-enum value is rejected and nothing is persisted."""
    with pytest.raises(ValueError):
        update_core_settings({"prices_display_mode": "gross"})

    # No persist: the value stays at its default on a fresh read, and the
    # invalid write left no file behind.
    assert get_core_settings()["prices_display_mode"] == "brutto"
    assert not os.path.exists(_settings_file(isolated_var_dir))


def test_prices_display_mode_rejection_does_not_persist_sibling_keys(isolated_var_dir):
    """A rejected value aborts the whole update — valid siblings are not saved."""
    with pytest.raises(ValueError):
        update_core_settings(
            {"provider_name": "Should Not Persist", "prices_display_mode": "gross"}
        )

    settings = get_core_settings()
    assert settings["provider_name"] == DEFAULT_CORE_SETTINGS["provider_name"]
    assert not os.path.exists(_settings_file(isolated_var_dir))


# ── S85.0: prices_mode_in_db (how the stored double is interpreted) ──────────


def test_prices_mode_in_db_defaults_to_netto():
    """S85.0 D7: the global storage-interpretation mode defaults to ``NETTO``."""
    settings = get_core_settings()
    assert settings["prices_mode_in_db"] == "NETTO"


def test_prices_mode_in_db_persists_brutto():
    """S85.0: ``BRUTTO`` is a valid value and round-trips across a fresh read."""
    merged = update_core_settings({"prices_mode_in_db": "BRUTTO"})
    assert merged["prices_mode_in_db"] == "BRUTTO"

    reread = get_core_settings()
    assert reread["prices_mode_in_db"] == "BRUTTO"


def test_prices_mode_in_db_rejects_unknown_value(isolated_var_dir):
    """S85.0: an out-of-enum value is rejected and nothing is persisted."""
    with pytest.raises(ValueError):
        update_core_settings({"prices_mode_in_db": "gross"})

    assert get_core_settings()["prices_mode_in_db"] == "NETTO"
    assert not os.path.exists(_settings_file(isolated_var_dir))


# ── S84: currency settings (default / active set / cross-rate base) ──────────


@pytest.fixture
def stub_catalog(monkeypatch):
    """Register a stub currency catalog so the validators can check membership."""
    from vbwd.services import core_settings_store

    catalog = {"EUR", "USD", "GBP", "JPY"}
    monkeypatch.setattr(
        core_settings_store,
        "_currency_catalog_provider",
        lambda: set(catalog),
    )
    return catalog


def test_currency_defaults():
    settings = get_core_settings()
    assert settings["default_currency"] == "EUR"
    assert settings["active_currencies"] == ["EUR"]
    assert settings["cross_rate_base"] == "default"


def test_cross_rate_base_rejects_unknown_value(stub_catalog):
    with pytest.raises(ValueError):
        update_core_settings({"cross_rate_base": "gbp"})


def test_cross_rate_base_accepts_usd(stub_catalog):
    update_core_settings({"active_currencies": ["EUR", "USD"]})
    merged = update_core_settings({"cross_rate_base": "usd"})
    assert merged["cross_rate_base"] == "usd"


def test_default_currency_rejected_when_not_in_catalog(stub_catalog):
    with pytest.raises(ValueError):
        update_core_settings(
            {"active_currencies": ["EUR", "XYZ"], "default_currency": "XYZ"}
        )


def test_default_currency_rejected_when_not_active(stub_catalog):
    # GBP is in the catalog but not in active_currencies → rejected.
    with pytest.raises(ValueError):
        update_core_settings({"default_currency": "GBP"})


def test_default_currency_accepted_when_in_catalog_and_active(stub_catalog):
    merged = update_core_settings(
        {"active_currencies": ["EUR", "USD"], "default_currency": "USD"}
    )
    assert merged["default_currency"] == "USD"
    assert "USD" in merged["active_currencies"]


def test_active_currencies_rejected_when_member_absent_from_catalog(stub_catalog):
    with pytest.raises(ValueError):
        update_core_settings({"active_currencies": ["EUR", "ZZZ"]})


def test_active_currencies_must_include_default(stub_catalog):
    # Removing the current default (EUR) from the active set is rejected.
    with pytest.raises(ValueError):
        update_core_settings({"active_currencies": ["USD"]})


def test_active_currencies_rejected_when_not_a_list(stub_catalog):
    with pytest.raises(ValueError):
        update_core_settings({"active_currencies": "EUR"})


def test_write_lands_in_core_namespace_path(isolated_var_dir):
    """S58.1: the write routes through the manager's ``core`` namespace,

    which lives at ``${VBWD_VAR_DIR}/core/vbwd_settings.json`` — the SAME
    on-disk path the hand-rolled IO used (behaviour-identical).
    """
    update_core_settings({"provider_name": "Namespaced GmbH"})
    expected_path = _settings_file(isolated_var_dir)
    assert os.path.exists(expected_path)
    on_disk = json.loads(open(expected_path, encoding="utf-8").read())
    assert on_disk["provider_name"] == "Namespaced GmbH"
