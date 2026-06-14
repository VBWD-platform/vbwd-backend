"""User-related schemas."""
from marshmallow import Schema, fields, validate

from vbwd.models.enums import AccountType


class UserSchema(Schema):
    """Schema for User model serialization."""

    id = fields.UUID(dump_only=True)
    email = fields.Email(required=True)
    status = fields.Str(dump_only=True)
    role = fields.Str(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    class Meta:
        """Schema metadata."""

        ordered = True


class UserDetailsSchema(Schema):
    """Schema for UserDetails model serialization."""

    id = fields.UUID(dump_only=True)
    user_id = fields.UUID(dump_only=True)
    first_name = fields.Str(allow_none=True, validate=validate.Length(max=100))
    last_name = fields.Str(allow_none=True, validate=validate.Length(max=100))
    phone = fields.Str(allow_none=True, validate=validate.Length(max=20))
    company = fields.Str(allow_none=True, validate=validate.Length(max=255))
    tax_number = fields.Str(allow_none=True, validate=validate.Length(max=100))
    account_type = fields.Str(validate=validate.OneOf(AccountType.values()))
    address_line_1 = fields.Str(allow_none=True, validate=validate.Length(max=255))
    address_line_2 = fields.Str(allow_none=True, validate=validate.Length(max=255))
    city = fields.Str(allow_none=True, validate=validate.Length(max=100))
    postal_code = fields.Str(allow_none=True, validate=validate.Length(max=20))
    country = fields.Str(allow_none=True, validate=validate.Length(max=2))
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    class Meta:
        """Schema metadata."""

        ordered = True


class UserDetailsUpdateSchema(Schema):
    """Schema for updating user details."""

    first_name = fields.Str(allow_none=True, validate=validate.Length(max=100))
    last_name = fields.Str(allow_none=True, validate=validate.Length(max=100))
    phone = fields.Str(allow_none=True, validate=validate.Length(max=20))
    company = fields.Str(allow_none=True, validate=validate.Length(max=255))
    tax_number = fields.Str(allow_none=True, validate=validate.Length(max=100))
    account_type = fields.Str(validate=validate.OneOf(AccountType.values()))
    address_line_1 = fields.Str(allow_none=True, validate=validate.Length(max=255))
    address_line_2 = fields.Str(allow_none=True, validate=validate.Length(max=255))
    city = fields.Str(allow_none=True, validate=validate.Length(max=100))
    postal_code = fields.Str(allow_none=True, validate=validate.Length(max=20))
    country = fields.Str(allow_none=True, validate=validate.Length(max=2))

    class Meta:
        """Schema metadata."""

        ordered = True


class UserProfileSchema(Schema):
    """Schema for complete user profile (user + details)."""

    user = fields.Nested(UserSchema)
    details = fields.Nested(UserDetailsSchema, allow_none=True)

    class Meta:
        """Schema metadata."""

        ordered = True
