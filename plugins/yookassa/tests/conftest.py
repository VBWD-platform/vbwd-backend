"""Shared fixtures for YooKassa plugin tests."""
import pytest
from unittest.mock import MagicMock

from src.sdk.interface import SDKConfig
from src.plugins.config_store import PluginConfigEntry


@pytest.fixture
def yookassa_config():
    """YooKassa plugin configuration dict."""
    return {
        "test_shop_id": "test_shop_123",
        "test_secret_key": "test_secret_456",
        "test_webhook_secret": "whsec_test_789",
        "sandbox": True,
    }


@pytest.fixture
def sdk_config(yookassa_config):
    """SDKConfig instance built from yookassa_config."""
    return SDKConfig(
        api_key=yookassa_config["test_shop_id"],
        api_secret=yookassa_config["test_secret_key"],
        sandbox=yookassa_config["sandbox"],
    )


@pytest.fixture
def mock_yookassa_api(mocker):
    """Mock requests module for YooKassa API calls.

    Returns the mock so tests can configure specific responses.
    """
    mock = mocker.patch("plugins.yookassa.sdk_adapter.requests")
    # Default: successful payment creation
    default_resp = mocker.MagicMock()
    default_resp.status_code = 200
    default_resp.json.return_value = {
        "id": "pay_default",
        "status": "pending",
        "confirmation": {"confirmation_url": "https://yookassa.ru/pay/default"},
    }
    mock.post.return_value = default_resp
    mock.get.return_value = default_resp
    return mock


@pytest.fixture
def mock_config_store(mocker, yookassa_config):
    """Mock PluginConfigStore with enabled YooKassa entry."""
    store = mocker.MagicMock()
    store.get_by_name.return_value = PluginConfigEntry(
        plugin_name="yookassa",
        status="enabled",
        config=yookassa_config,
    )
    store.get_config.return_value = yookassa_config
    return store


@pytest.fixture
def mock_config_store_disabled(mocker):
    """Config store returning disabled YooKassa plugin."""
    store = mocker.MagicMock()
    store.get_by_name.return_value = PluginConfigEntry(
        plugin_name="yookassa", status="disabled"
    )
    return store
