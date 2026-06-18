"""Unit tests for the file-backed core auth rate-limits store.

TDD RED: written before ``vbwd/services/core_rate_limits_store.py`` exists.

Mirrors the core_settings_store contract: the per-route auth rate-limit caps
live in code as compiled defaults, are overridable from an external host-mounted
file at ``${VBWD_VAR_DIR}/core/rate_limits.json``, and a missing/corrupt/non-dict
file degrades to defaults without raising.
"""
import json
import os

import pytest

from vbwd.services.core_rate_limits_store import (
    DEFAULT_AUTH_RATE_LIMITS,
    get_auth_rate_limit,
    get_auth_rate_limits,
)


@pytest.fixture(autouse=True)
def isolated_var_dir(tmp_path, monkeypatch):
    """Point the store at a throwaway ``VBWD_VAR_DIR`` for each test."""
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    return tmp_path


def _rate_limits_file(var_dir) -> str:
    return os.path.join(str(var_dir), "core", "rate_limits.json")


def _write_file(var_dir, payload) -> None:
    path = _rate_limits_file(var_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def test_defaults_when_file_absent():
    assert get_auth_rate_limits() == DEFAULT_AUTH_RATE_LIMITS
    # A read must never create the file.
    assert not os.path.exists(_rate_limits_file(os.environ["VBWD_VAR_DIR"]))


def test_default_values_are_the_contract():
    assert DEFAULT_AUTH_RATE_LIMITS == {
        "register": "15 per minute",
        "login": "30 per minute",
        "check_email": "60 per minute",
        "forgot_password": "10 per minute",
        "reset_password": "10 per minute",
    }


def test_get_single_returns_default(monkeypatch):
    assert get_auth_rate_limit("login") == "30 per minute"
    assert get_auth_rate_limit("register") == "15 per minute"


def test_written_override_changes_returned_value(isolated_var_dir):
    _write_file(isolated_var_dir, {"login": "5 per minute"})
    limits = get_auth_rate_limits()
    assert limits["login"] == "5 per minute"
    # Unspecified keys fall back to defaults.
    assert limits["register"] == "15 per minute"
    assert get_auth_rate_limit("login") == "5 per minute"


def test_unknown_keys_in_file_are_ignored(isolated_var_dir):
    _write_file(isolated_var_dir, {"login": "7 per minute", "bogus": "1 per second"})
    limits = get_auth_rate_limits()
    assert "bogus" not in limits
    assert limits["login"] == "7 per minute"


def test_corrupt_file_degrades_to_defaults(isolated_var_dir):
    path = _rate_limits_file(isolated_var_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{ not valid json")
    assert get_auth_rate_limits() == DEFAULT_AUTH_RATE_LIMITS


def test_non_dict_file_degrades_to_defaults(isolated_var_dir):
    _write_file(isolated_var_dir, ["15 per minute"])
    assert get_auth_rate_limits() == DEFAULT_AUTH_RATE_LIMITS
