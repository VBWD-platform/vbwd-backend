"""Authentication-related schemas."""
from marshmallow import Schema, fields, validate, validates, ValidationError
import re


class RegisterRequestSchema(Schema):
    """Schema for user registration request."""

    email = fields.Email(
        required=True,
        validate=validate.Length(max=255),
        error_messages={
            "required": "Email is required",
            "invalid": "Invalid email format",
        },
    )
    password = fields.Str(
        required=True,
        validate=validate.Length(min=8),
        load_only=True,  # Never serialize password
        error_messages={
            "required": "Password is required",
            "invalid": "Password must be at least 8 characters",
        },
    )

    @validates("password")
    def validate_password(self, value):
        """Validate password strength.

        Args:
            value: Password to validate

        Raises:
            ValidationError: If password doesn't meet requirements
        """
        if len(value) < 8:
            raise ValidationError("Password must be at least 8 characters long")

        if not re.search(r"[a-z]", value):
            raise ValidationError("Password must contain at least one lowercase letter")

        if not re.search(r"[A-Z]", value):
            raise ValidationError("Password must contain at least one uppercase letter")

        if not re.search(r"\d", value):
            raise ValidationError("Password must contain at least one number")

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', value):
            raise ValidationError(
                "Password must contain at least one special character"
            )


class LoginRequestSchema(Schema):
    """Schema for user login request."""

    email = fields.Email(
        required=True,
        error_messages={
            "required": "Email is required",
            "invalid": "Invalid email format",
        },
    )
    password = fields.Str(
        required=True,
        load_only=True,  # Never serialize password
        error_messages={"required": "Password is required"},
    )


class RoleSchema(Schema):
    """Schema for role in auth response."""

    id = fields.Str()
    slug = fields.Str()
    name = fields.Str()


class UserDataSchema(Schema):
    """Schema for user data in auth response."""

    id = fields.Str(required=True)
    email = fields.Email(required=True)
    name = fields.Str(allow_none=True)
    role = fields.Str(allow_none=True)
    is_admin = fields.Bool(allow_none=True)
    access_levels = fields.List(
        fields.Nested(RoleSchema), allow_none=True
    )
    permissions = fields.List(fields.Str(), allow_none=True)
    user_access_levels = fields.List(
        fields.Nested(RoleSchema), allow_none=True
    )
    user_permissions = fields.List(fields.Str(), allow_none=True)


class AuthResponseSchema(Schema):
    """Schema for authentication response."""

    success = fields.Bool(required=True)
    token = fields.Str(allow_none=True)
    user_id = fields.UUID(allow_none=True)
    error = fields.Str(allow_none=True)
    user = fields.Nested(UserDataSchema, allow_none=True)
