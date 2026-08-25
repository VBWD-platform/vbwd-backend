"""Tests for user schemas."""
import pytest
from uuid import uuid4
from types import SimpleNamespace
from vbwd.schemas.user_schemas import (
    UserDetailsSchema,
    UserDetailsUpdateSchema,
    UserProfileSchema,
)


class TestUserDetailsSchema:
    """Tests for UserDetailsSchema."""

    def test_serializes_model_fields(self):
        """UserDetailsSchema should serialize UserDetails model without error."""
        details = SimpleNamespace(
            id=uuid4(),
            user_id=uuid4(),
            first_name="John",
            last_name="Doe",
            phone="+1234567890",
            company="Acme Corp",
            tax_number="DE123456789",
            address_line_1="123 Main St",
            address_line_2="Apt 4B",
            city="New York",
            postal_code="10001",
            country="US",
            created_at=None,
            updated_at=None,
        )

        schema = UserDetailsSchema()
        result = schema.dump(details)

        assert result["first_name"] == "John"
        assert result["last_name"] == "Doe"
        assert result["company"] == "Acme Corp"
        assert result["address_line_1"] == "123 Main St"
        assert result["address_line_2"] == "Apt 4B"
        assert result["city"] == "New York"
        assert result["postal_code"] == "10001"
        assert result["country"] == "US"

    def test_serializes_none_values(self):
        """UserDetailsSchema should handle None values."""
        details = SimpleNamespace(
            id=uuid4(),
            user_id=uuid4(),
            first_name=None,
            last_name=None,
            phone=None,
            company=None,
            tax_number=None,
            address_line_1=None,
            address_line_2=None,
            city=None,
            postal_code=None,
            country=None,
            created_at=None,
            updated_at=None,
        )

        schema = UserDetailsSchema()
        result = schema.dump(details)

        assert result["first_name"] is None
        assert result["address_line_1"] is None
        assert result["address_line_2"] is None

    def test_does_not_have_removed_fields(self):
        """UserDetailsSchema should not have legacy address or vat_number fields."""
        schema = UserDetailsSchema()
        field_names = set(schema.fields.keys())

        assert "address" not in field_names
        assert "vat_number" not in field_names

    def test_has_company_field(self):
        """UserDetailsSchema should include company field."""
        schema = UserDetailsSchema()
        assert "company" in schema.fields

    def test_dump_includes_state(self):
        """UserDetailsSchema should serialize the state/region field."""
        details = SimpleNamespace(
            id=uuid4(),
            user_id=uuid4(),
            first_name="John",
            last_name="Doe",
            phone=None,
            company=None,
            tax_number=None,
            address_line_1="123 Main St",
            address_line_2=None,
            city="Los Angeles",
            state="California",
            postal_code="90001",
            country="US",
            created_at=None,
            updated_at=None,
        )

        schema = UserDetailsSchema()
        result = schema.dump(details)

        assert result["state"] == "California"


class TestUserDetailsUpdateSchema:
    """Tests for UserDetailsUpdateSchema."""

    def test_loads_valid_data(self):
        """UserDetailsUpdateSchema should load valid update data."""
        schema = UserDetailsUpdateSchema()
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "address_line_1": "123 Main St",
            "address_line_2": "Apt 4B",
            "city": "New York",
            "postal_code": "10001",
            "country": "US",
        }

        result = schema.load(data)

        assert result["first_name"] == "John"
        assert result["address_line_1"] == "123 Main St"
        assert result["country"] == "US"

    def test_validates_country_length(self):
        """UserDetailsUpdateSchema should reject country > 2 chars."""
        from marshmallow import ValidationError

        schema = UserDetailsUpdateSchema()
        data = {"country": "USA"}  # 3 chars, should fail

        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)

        assert "country" in exc_info.value.messages

    def test_does_not_have_removed_fields(self):
        """UserDetailsUpdateSchema should not have legacy address or vat_number fields."""
        schema = UserDetailsUpdateSchema()
        field_names = set(schema.fields.keys())

        assert "address" not in field_names
        assert "vat_number" not in field_names

    def test_has_company_field(self):
        """UserDetailsUpdateSchema should include company field."""
        schema = UserDetailsUpdateSchema()
        assert "company" in schema.fields

    def test_has_tax_number_field(self):
        """UserDetailsUpdateSchema should include tax_number field."""
        schema = UserDetailsUpdateSchema()
        assert "tax_number" in schema.fields

    def test_loads_optional_fields(self):
        """UserDetailsUpdateSchema should accept company and tax_number as optional."""
        schema = UserDetailsUpdateSchema()
        data = {
            "first_name": "Jane",
            "company": "Acme Corp",
            "tax_number": "DE123456789",
        }
        result = schema.load(data)
        assert result["company"] == "Acme Corp"
        assert result["tax_number"] == "DE123456789"

    def test_has_account_type_field(self):
        """UserDetailsUpdateSchema should include account_type field (S74)."""
        schema = UserDetailsUpdateSchema()
        assert "account_type" in schema.fields

    def test_loads_state_field(self):
        """UserDetailsUpdateSchema should accept a state/region value."""
        schema = UserDetailsUpdateSchema()
        result = schema.load({"state": "California"})
        assert result["state"] == "California"

    def test_rejects_state_over_max_length(self):
        """UserDetailsUpdateSchema should reject a state longer than 100 chars."""
        from marshmallow import ValidationError

        schema = UserDetailsUpdateSchema()
        with pytest.raises(ValidationError) as exc_info:
            schema.load({"state": "x" * 101})
        assert "state" in exc_info.value.messages

    def test_accepts_valid_account_type(self):
        schema = UserDetailsUpdateSchema()
        result = schema.load({"account_type": "business"})
        assert result["account_type"] == "business"

    def test_rejects_unknown_account_type(self):
        from marshmallow import ValidationError

        schema = UserDetailsUpdateSchema()
        with pytest.raises(ValidationError) as exc_info:
            schema.load({"account_type": "enterprise"})
        assert "account_type" in exc_info.value.messages


class TestUserProfileSchema:
    """Tests for UserProfileSchema."""

    def test_serializes_user_and_details(self):
        """UserProfileSchema should serialize nested user and details."""
        user = SimpleNamespace(
            id=uuid4(),
            email="test@example.com",
            status="active",
            role="user",
            created_at=None,
            updated_at=None,
        )

        details = SimpleNamespace(
            id=uuid4(),
            user_id=user.id,
            first_name="Test",
            last_name="User",
            phone=None,
            company=None,
            tax_number=None,
            address_line_1="123 Main St",
            address_line_2=None,
            city="New York",
            postal_code="10001",
            country="US",
            created_at=None,
            updated_at=None,
        )

        schema = UserProfileSchema()
        result = schema.dump({"user": user, "details": details})

        assert result["user"]["email"] == "test@example.com"
        assert result["details"]["first_name"] == "Test"
        assert result["details"]["address_line_1"] == "123 Main St"

    def test_handles_null_details(self):
        """UserProfileSchema should handle null details."""
        user = SimpleNamespace(
            id=uuid4(),
            email="test@example.com",
            status="active",
            role="user",
            created_at=None,
            updated_at=None,
        )

        schema = UserProfileSchema()
        result = schema.dump({"user": user, "details": None})

        assert result["user"]["email"] == "test@example.com"
        assert result["details"] is None
