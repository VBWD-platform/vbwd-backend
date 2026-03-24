"""Tests for SDK adapter layer (Sprint 14)."""
import pytest
from decimal import Decimal
from unittest.mock import Mock, patch
import json


class TestIdempotencyService:
    """Tests for IdempotencyService."""

    def test_generate_key_creates_deterministic_key(self):
        """generate_key() creates deterministic key from inputs."""
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        service = IdempotencyService(mock_redis)

        key1 = service.generate_key("stripe", "create_payment", "100", "USD")
        key2 = service.generate_key("stripe", "create_payment", "100", "USD")

        assert key1 == key2
        assert len(key1) == 32  # SHA256 truncated to 32 chars

    def test_generate_key_different_inputs_different_keys(self):
        """Different inputs produce different keys."""
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        service = IdempotencyService(mock_redis)

        key1 = service.generate_key("stripe", "create_payment", "100", "USD")
        key2 = service.generate_key("stripe", "create_payment", "200", "USD")

        assert key1 != key2

    def test_check_returns_none_for_new_key(self):
        """New key returns None."""
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        mock_redis.get.return_value = None

        service = IdempotencyService(mock_redis)
        result = service.check("new_key")

        assert result is None
        mock_redis.get.assert_called_once_with("idempotency:new_key")

    def test_check_returns_cached_response(self):
        """Existing key returns cached response."""
        from vbwd.sdk.idempotency_service import IdempotencyService

        cached_data = {"success": True, "data": {"payment_id": "pi_123"}}
        mock_redis = Mock()
        mock_redis.get.return_value = json.dumps(cached_data).encode()

        service = IdempotencyService(mock_redis)
        result = service.check("existing_key")

        assert result == cached_data

    def test_store_saves_response_with_default_ttl(self):
        """store() caches response with default TTL."""
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        service = IdempotencyService(mock_redis)

        response = {"success": True, "data": {"payment_id": "pi_123"}}
        service.store("my_key", response)

        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args[0]
        assert args[0] == "idempotency:my_key"
        assert args[1] == 86400  # Default TTL
        assert json.loads(args[2]) == response

    def test_store_saves_response_with_custom_ttl(self):
        """store() caches response with custom TTL."""
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        service = IdempotencyService(mock_redis)

        response = {"success": True}
        service.store("my_key", response, ttl=3600)

        args = mock_redis.setex.call_args[0]
        assert args[1] == 3600

    def test_delete_removes_key(self):
        """delete() removes key from cache."""
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        service = IdempotencyService(mock_redis)

        service.delete("my_key")

        mock_redis.delete.assert_called_once_with("idempotency:my_key")


class TestSDKConfig:
    """Tests for SDKConfig dataclass."""

    def test_config_with_required_fields(self):
        """SDKConfig requires api_key."""
        from vbwd.sdk.interface import SDKConfig

        config = SDKConfig(api_key="sk_test_123")

        assert config.api_key == "sk_test_123"
        assert config.api_secret is None
        assert config.sandbox is True
        assert config.timeout == 30
        assert config.max_retries == 3

    def test_config_with_all_fields(self):
        """SDKConfig accepts all fields."""
        from vbwd.sdk.interface import SDKConfig

        config = SDKConfig(
            api_key="sk_test_123",
            api_secret="secret",
            sandbox=False,
            timeout=60,
            max_retries=5,
        )

        assert config.api_secret == "secret"
        assert config.sandbox is False
        assert config.timeout == 60
        assert config.max_retries == 5


class TestSDKResponse:
    """Tests for SDKResponse dataclass."""

    def test_response_success(self):
        """SDKResponse for successful operation."""
        from vbwd.sdk.interface import SDKResponse

        response = SDKResponse(success=True, data={"payment_id": "pi_123"})

        assert response.success is True
        assert response.data == {"payment_id": "pi_123"}
        assert response.error is None

    def test_response_failure(self):
        """SDKResponse for failed operation."""
        from vbwd.sdk.interface import SDKResponse

        response = SDKResponse(
            success=False, error="Card declined", error_code="card_declined"
        )

        assert response.success is False
        assert response.error == "Card declined"
        assert response.error_code == "card_declined"

    def test_response_to_dict(self):
        """SDKResponse can convert to dict."""
        from vbwd.sdk.interface import SDKResponse

        response = SDKResponse(success=True, data={"id": "123"})
        result = response.to_dict()

        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["data"] == {"id": "123"}


class TestISDKAdapter:
    """Tests for ISDKAdapter interface."""

    def test_adapter_has_create_payment_intent(self):
        """Adapter must implement create_payment_intent."""
        from vbwd.sdk.interface import ISDKAdapter

        assert hasattr(ISDKAdapter, "create_payment_intent")

    def test_adapter_has_capture_payment(self):
        """Adapter must implement capture_payment."""
        from vbwd.sdk.interface import ISDKAdapter

        assert hasattr(ISDKAdapter, "capture_payment")

    def test_adapter_has_refund_payment(self):
        """Adapter must implement refund_payment."""
        from vbwd.sdk.interface import ISDKAdapter

        assert hasattr(ISDKAdapter, "refund_payment")

    def test_adapter_has_get_payment_status(self):
        """Adapter must implement get_payment_status."""
        from vbwd.sdk.interface import ISDKAdapter

        assert hasattr(ISDKAdapter, "get_payment_status")

    def test_adapter_has_provider_name(self):
        """Adapter must have provider_name property."""
        from vbwd.sdk.interface import ISDKAdapter

        assert hasattr(ISDKAdapter, "provider_name")


class TestMockSDKAdapter:
    """Tests for MockSDKAdapter."""

    def test_mock_adapter_implements_interface(self):
        """MockSDKAdapter implements ISDKAdapter."""
        from vbwd.sdk.interface import ISDKAdapter
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        assert isinstance(adapter, ISDKAdapter)

    def test_mock_adapter_provider_name(self):
        """MockSDKAdapter has provider_name 'mock'."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        assert adapter.provider_name == "mock"

    def test_create_payment_intent_succeeds_by_default(self):
        """create_payment_intent returns success by default."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        response = adapter.create_payment_intent(
            amount=Decimal("29.99"), currency="USD", metadata={"user_id": "user_123"}
        )

        assert response.success is True
        assert "payment_intent_id" in response.data
        assert response.data["payment_intent_id"].startswith("pi_mock_")

    def test_create_payment_intent_can_fail(self):
        """create_payment_intent can be configured to fail."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter(should_fail=True)
        response = adapter.create_payment_intent(
            amount=Decimal("29.99"), currency="USD", metadata={}
        )

        assert response.success is False
        assert response.error is not None

    def test_create_payment_intent_with_idempotency_key(self):
        """Same idempotency key returns same payment_intent_id."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        response1 = adapter.create_payment_intent(
            amount=Decimal("29.99"),
            currency="USD",
            metadata={},
            idempotency_key="key_123",
        )
        response2 = adapter.create_payment_intent(
            amount=Decimal("29.99"),
            currency="USD",
            metadata={},
            idempotency_key="key_123",
        )

        assert (
            response1.data["payment_intent_id"] == response2.data["payment_intent_id"]
        )

    def test_capture_payment_succeeds(self):
        """capture_payment returns success for valid intent."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        # First create a payment intent
        create_response = adapter.create_payment_intent(
            amount=Decimal("29.99"), currency="USD", metadata={}
        )
        payment_intent_id = create_response.data["payment_intent_id"]

        # Then capture it
        response = adapter.capture_payment(payment_intent_id)

        assert response.success is True
        assert response.data["status"] == "captured"

    def test_capture_payment_fails_for_unknown_intent(self):
        """capture_payment fails for unknown payment_intent_id."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        response = adapter.capture_payment("pi_unknown")

        assert response.success is False
        assert "not found" in response.error.lower()

    def test_refund_payment_full_refund(self):
        """refund_payment performs full refund when amount not specified."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        # Create and capture first
        create_response = adapter.create_payment_intent(
            amount=Decimal("29.99"), currency="USD", metadata={}
        )
        payment_intent_id = create_response.data["payment_intent_id"]
        adapter.capture_payment(payment_intent_id)

        # Then refund
        response = adapter.refund_payment(payment_intent_id)

        assert response.success is True
        assert response.data["refund_id"].startswith("re_mock_")
        assert response.data["amount"] == Decimal("29.99")

    def test_refund_payment_partial_refund(self):
        """refund_payment performs partial refund when amount specified."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        # Create and capture first
        create_response = adapter.create_payment_intent(
            amount=Decimal("29.99"), currency="USD", metadata={}
        )
        payment_intent_id = create_response.data["payment_intent_id"]
        adapter.capture_payment(payment_intent_id)

        # Partial refund
        response = adapter.refund_payment(payment_intent_id, amount=Decimal("10.00"))

        assert response.success is True
        assert response.data["amount"] == Decimal("10.00")

    def test_get_payment_status(self):
        """get_payment_status returns current status."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        create_response = adapter.create_payment_intent(
            amount=Decimal("29.99"), currency="USD", metadata={}
        )
        payment_intent_id = create_response.data["payment_intent_id"]

        response = adapter.get_payment_status(payment_intent_id)

        assert response.success is True
        assert response.data["status"] == "created"

    def test_get_payment_status_after_capture(self):
        """get_payment_status returns 'captured' after capture."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        create_response = adapter.create_payment_intent(
            amount=Decimal("29.99"), currency="USD", metadata={}
        )
        payment_intent_id = create_response.data["payment_intent_id"]
        adapter.capture_payment(payment_intent_id)

        response = adapter.get_payment_status(payment_intent_id)

        assert response.data["status"] == "captured"

    def test_mock_adapter_tracks_calls(self):
        """MockSDKAdapter tracks all method calls."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        adapter.create_payment_intent(Decimal("29.99"), "USD", {})
        adapter.create_payment_intent(Decimal("49.99"), "EUR", {})

        assert len(adapter.calls) == 2
        assert adapter.calls[0]["method"] == "create_payment_intent"
        assert adapter.calls[0]["amount"] == Decimal("29.99")
        assert adapter.calls[1]["amount"] == Decimal("49.99")

    def test_mock_adapter_set_should_fail(self):
        """MockSDKAdapter can toggle failure mode."""
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        adapter = MockSDKAdapter()
        assert adapter.create_payment_intent(Decimal("10"), "USD", {}).success is True

        adapter.set_should_fail(True)
        assert adapter.create_payment_intent(Decimal("10"), "USD", {}).success is False

        adapter.set_should_fail(False)
        assert adapter.create_payment_intent(Decimal("10"), "USD", {}).success is True


class TestSDKAdapterRegistry:
    """Tests for SDKAdapterRegistry."""

    def test_register_adapter(self):
        """Register adapter by provider name."""
        from vbwd.sdk.registry import SDKAdapterRegistry
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        registry = SDKAdapterRegistry()
        adapter = MockSDKAdapter()

        registry.register("mock", adapter)

        assert registry.has("mock")

    def test_get_adapter_returns_registered(self):
        """Get returns registered adapter."""
        from vbwd.sdk.registry import SDKAdapterRegistry
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        registry = SDKAdapterRegistry()
        adapter = MockSDKAdapter()
        registry.register("mock", adapter)

        result = registry.get("mock")

        assert result is adapter

    def test_get_adapter_raises_for_unknown(self):
        """Unknown provider raises ValueError."""
        from vbwd.sdk.registry import SDKAdapterRegistry

        registry = SDKAdapterRegistry()

        with pytest.raises(ValueError) as exc_info:
            registry.get("unknown")

        assert "unknown" in str(exc_info.value).lower()

    def test_list_providers(self):
        """list_providers returns all registered names."""
        from vbwd.sdk.registry import SDKAdapterRegistry
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        registry = SDKAdapterRegistry()
        registry.register("mock", MockSDKAdapter())
        registry.register("stripe", MockSDKAdapter())

        providers = registry.list_providers()

        assert "mock" in providers
        assert "stripe" in providers
        assert len(providers) == 2

    def test_has_returns_false_for_unknown(self):
        """has() returns False for unknown provider."""
        from vbwd.sdk.registry import SDKAdapterRegistry

        registry = SDKAdapterRegistry()

        assert registry.has("unknown") is False

    def test_unregister_adapter(self):
        """unregister() removes adapter."""
        from vbwd.sdk.registry import SDKAdapterRegistry
        from vbwd.sdk.mock_adapter import MockSDKAdapter

        registry = SDKAdapterRegistry()
        registry.register("mock", MockSDKAdapter())

        registry.unregister("mock")

        assert registry.has("mock") is False


class TestBaseSDKAdapter:
    """Tests for BaseSDKAdapter."""

    def test_base_adapter_checks_idempotency_before_operation(self):
        """Base adapter checks idempotency before calling provider."""
        from vbwd.sdk.base import BaseSDKAdapter
        from vbwd.sdk.interface import SDKConfig, SDKResponse
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        cached_response = {"success": True, "data": {"payment_intent_id": "pi_cached"}}
        mock_redis.get.return_value = json.dumps(cached_response).encode()

        idempotency = IdempotencyService(mock_redis)
        config = SDKConfig(api_key="test")

        # Create concrete implementation
        class TestAdapter(BaseSDKAdapter):
            provider_name = "test"

            def create_payment_intent(
                self, amount, currency, metadata, idempotency_key=None
            ):
                def _create():
                    return SDKResponse(
                        success=True, data={"payment_intent_id": "pi_new"}
                    )

                return self._with_idempotency(idempotency_key, _create)

            def capture_payment(self, payment_intent_id, idempotency_key=None):
                return SDKResponse(success=True)

            def release_authorization(self, payment_intent_id):
                return SDKResponse(success=True)

            def refund_payment(
                self, payment_intent_id, amount=None, idempotency_key=None
            ):
                return SDKResponse(success=True)

            def get_payment_status(self, payment_intent_id):
                return SDKResponse(success=True)

        adapter = TestAdapter(config, idempotency)
        response = adapter.create_payment_intent(
            Decimal("29.99"), "USD", {}, idempotency_key="test_key"
        )

        # Should return cached response, not create new
        assert response.data["payment_intent_id"] == "pi_cached"

    def test_base_adapter_stores_successful_response(self):
        """Successful responses are cached for idempotency."""
        from vbwd.sdk.base import BaseSDKAdapter
        from vbwd.sdk.interface import SDKConfig, SDKResponse
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        mock_redis.get.return_value = None  # No cached response

        idempotency = IdempotencyService(mock_redis)
        config = SDKConfig(api_key="test")

        class TestAdapter(BaseSDKAdapter):
            provider_name = "test"

            def create_payment_intent(
                self, amount, currency, metadata, idempotency_key=None
            ):
                def _create():
                    return SDKResponse(
                        success=True, data={"payment_intent_id": "pi_new"}
                    )

                return self._with_idempotency(idempotency_key, _create)

            def capture_payment(self, payment_intent_id, idempotency_key=None):
                return SDKResponse(success=True)

            def release_authorization(self, payment_intent_id):
                return SDKResponse(success=True)

            def refund_payment(
                self, payment_intent_id, amount=None, idempotency_key=None
            ):
                return SDKResponse(success=True)

            def get_payment_status(self, payment_intent_id):
                return SDKResponse(success=True)

        adapter = TestAdapter(config, idempotency)
        adapter.create_payment_intent(
            Decimal("29.99"), "USD", {}, idempotency_key="test_key"
        )

        # Should have stored the response
        mock_redis.setex.assert_called_once()

    def test_base_adapter_does_not_store_failed_response(self):
        """Failed responses are not cached."""
        from vbwd.sdk.base import BaseSDKAdapter
        from vbwd.sdk.interface import SDKConfig, SDKResponse
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        mock_redis.get.return_value = None

        idempotency = IdempotencyService(mock_redis)
        config = SDKConfig(api_key="test")

        class TestAdapter(BaseSDKAdapter):
            provider_name = "test"

            def create_payment_intent(
                self, amount, currency, metadata, idempotency_key=None
            ):
                def _create():
                    return SDKResponse(success=False, error="Failed")

                return self._with_idempotency(idempotency_key, _create)

            def capture_payment(self, payment_intent_id, idempotency_key=None):
                return SDKResponse(success=True)

            def release_authorization(self, payment_intent_id):
                return SDKResponse(success=True)

            def refund_payment(
                self, payment_intent_id, amount=None, idempotency_key=None
            ):
                return SDKResponse(success=True)

            def get_payment_status(self, payment_intent_id):
                return SDKResponse(success=True)

        adapter = TestAdapter(config, idempotency)
        adapter.create_payment_intent(
            Decimal("29.99"), "USD", {}, idempotency_key="test_key"
        )

        # Should NOT have stored the failed response
        mock_redis.setex.assert_not_called()

    def test_base_adapter_retries_on_transient_error(self):
        """Base adapter retries transient failures."""
        from vbwd.sdk.base import BaseSDKAdapter, TransientError
        from vbwd.sdk.interface import SDKConfig, SDKResponse
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        mock_redis.get.return_value = None

        idempotency = IdempotencyService(mock_redis)
        config = SDKConfig(api_key="test", max_retries=3)

        call_count = 0

        class TestAdapter(BaseSDKAdapter):
            provider_name = "test"

            def create_payment_intent(
                self, amount, currency, metadata, idempotency_key=None
            ):
                def _create():
                    nonlocal call_count
                    call_count += 1
                    if call_count < 3:
                        raise TransientError("Temporary failure")
                    return SDKResponse(
                        success=True, data={"payment_intent_id": "pi_123"}
                    )

                return self._with_retry(_create)

            def capture_payment(self, payment_intent_id, idempotency_key=None):
                return SDKResponse(success=True)

            def release_authorization(self, payment_intent_id):
                return SDKResponse(success=True)

            def refund_payment(
                self, payment_intent_id, amount=None, idempotency_key=None
            ):
                return SDKResponse(success=True)

            def get_payment_status(self, payment_intent_id):
                return SDKResponse(success=True)

        adapter = TestAdapter(config, idempotency)

        with patch("time.sleep"):  # Don't actually sleep in tests
            response = adapter.create_payment_intent(Decimal("29.99"), "USD", {})

        assert response.success is True
        assert call_count == 3  # Retried twice, succeeded on third

    def test_base_adapter_gives_up_after_max_retries(self):
        """Base adapter gives up after max retries."""
        from vbwd.sdk.base import BaseSDKAdapter, TransientError
        from vbwd.sdk.interface import SDKConfig, SDKResponse
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        mock_redis.get.return_value = None

        idempotency = IdempotencyService(mock_redis)
        config = SDKConfig(api_key="test", max_retries=2)

        class TestAdapter(BaseSDKAdapter):
            provider_name = "test"

            def create_payment_intent(
                self, amount, currency, metadata, idempotency_key=None
            ):
                def _create():
                    raise TransientError("Always fails")

                return self._with_retry(_create)

            def capture_payment(self, payment_intent_id, idempotency_key=None):
                return SDKResponse(success=True)

            def release_authorization(self, payment_intent_id):
                return SDKResponse(success=True)

            def refund_payment(
                self, payment_intent_id, amount=None, idempotency_key=None
            ):
                return SDKResponse(success=True)

            def get_payment_status(self, payment_intent_id):
                return SDKResponse(success=True)

        adapter = TestAdapter(config, idempotency)

        with patch("time.sleep"):
            with pytest.raises(TransientError):
                adapter.create_payment_intent(Decimal("29.99"), "USD", {})

    def test_base_adapter_without_idempotency_key(self):
        """Operations work without idempotency key."""
        from vbwd.sdk.base import BaseSDKAdapter
        from vbwd.sdk.interface import SDKConfig, SDKResponse
        from vbwd.sdk.idempotency_service import IdempotencyService

        mock_redis = Mock()
        idempotency = IdempotencyService(mock_redis)
        config = SDKConfig(api_key="test")

        class TestAdapter(BaseSDKAdapter):
            provider_name = "test"

            def create_payment_intent(
                self, amount, currency, metadata, idempotency_key=None
            ):
                def _create():
                    return SDKResponse(
                        success=True, data={"payment_intent_id": "pi_123"}
                    )

                return self._with_idempotency(idempotency_key, _create)

            def capture_payment(self, payment_intent_id, idempotency_key=None):
                return SDKResponse(success=True)

            def release_authorization(self, payment_intent_id):
                return SDKResponse(success=True)

            def refund_payment(
                self, payment_intent_id, amount=None, idempotency_key=None
            ):
                return SDKResponse(success=True)

            def get_payment_status(self, payment_intent_id):
                return SDKResponse(success=True)

        adapter = TestAdapter(config, idempotency)
        response = adapter.create_payment_intent(Decimal("29.99"), "USD", {})

        assert response.success is True
        # Should not check or store idempotency
        mock_redis.get.assert_not_called()
        mock_redis.setex.assert_not_called()
