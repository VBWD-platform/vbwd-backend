"""Multi-key store: add (platform + plugin), reject invalid, remove by id."""
import pytest

from vbwd.security.licensing.license_key import LicenseStatus
from vbwd.security.licensing.license_store import (
    LicenseKeyRejected,
    LicenseStore,
    read_held_envelope,
)
from vbwd.security.licensing.verifier import LicenseVerifier

from .conftest import FIXTURE_INSTANCE_ID, make_license_key, mint_envelope


@pytest.fixture
def store(tmp_path, signer, fixed_clock):
    verifier = LicenseVerifier(signer, FIXTURE_INSTANCE_ID, fixed_clock)
    return LicenseStore(str(tmp_path), verifier)


def test_add_two_keys_lists_both(store, signer):
    platform = make_license_key(key_id="key-platform", scope=("*",))
    plugin = make_license_key(key_id="key-plugin", scope=("marketplace",))
    store.add(mint_envelope(platform, signer))
    store.add(mint_envelope(plugin, signer))

    listed = {key.key_id: status for key, status in store.all()}
    assert listed == {
        "key-platform": LicenseStatus.VALID,
        "key-plugin": LicenseStatus.VALID,
    }


def test_add_invalid_is_rejected_and_not_persisted(store, signer):
    envelope = mint_envelope(make_license_key(), signer)
    tampered = envelope[:-2] + ("A" if envelope[-1] != "A" else "B")
    with pytest.raises(LicenseKeyRejected) as excinfo:
        store.add(tampered)
    assert excinfo.value.status is LicenseStatus.INVALID_SIGNATURE
    assert store.all() == []


def test_remove_by_id(store, signer):
    store.add(mint_envelope(make_license_key(key_id="key-x"), signer))
    assert store.remove("key-x") is True
    assert store.all() == []
    assert store.remove("key-x") is False


def test_read_held_envelope_returns_none_when_no_keys(tmp_path):
    assert read_held_envelope(str(tmp_path)) is None
    assert read_held_envelope(str(tmp_path / "does-not-exist")) is None


def test_read_held_envelope_returns_the_raw_envelope(store, signer, tmp_path):
    envelope = mint_envelope(make_license_key(key_id="key-x"), signer)
    store.add(envelope)

    assert read_held_envelope(str(tmp_path)) == envelope
