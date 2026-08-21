"""Unit tests for UserService."""
import pytest
from unittest.mock import Mock
from uuid import uuid4
from vbwd.models.user import User
from vbwd.models.user_details import UserDetails
from vbwd.models.enums import UserStatus, UserRole


class TestUserService:
    """Test UserService methods"""

    @pytest.fixture
    def mock_user_repo(self):
        """Mock UserRepository."""
        repo = Mock()
        repo.find_by_id = Mock()
        repo.update = Mock()
        return repo

    @pytest.fixture
    def mock_user_details_repo(self):
        """Mock UserDetailsRepository."""
        repo = Mock()
        repo.find_by_user_id = Mock()
        repo.save = Mock()
        repo.update = Mock()
        return repo

    @pytest.fixture
    def user_service(self, mock_user_repo, mock_user_details_repo):
        """Create UserService with mocked dependencies."""
        from vbwd.services.user_service import UserService

        return UserService(
            user_repository=mock_user_repo,
            user_details_repository=mock_user_details_repo,
            token_service=Mock(),
        )

    def test_get_user_returns_user(self, user_service, mock_user_repo):
        """Test get_user returns user by ID."""
        user_id = uuid4()

        # Mock user
        mock_user = User()
        mock_user.id = user_id
        mock_user.email = "test@example.com"
        mock_user.status = UserStatus.ACTIVE
        mock_user.role = UserRole.USER
        mock_user_repo.find_by_id.return_value = mock_user

        # Call get_user
        result = user_service.get_user(user_id)

        # Assertions
        assert result is not None
        assert result.id == user_id
        assert result.email == "test@example.com"

        # Verify repository was called
        mock_user_repo.find_by_id.assert_called_once_with(user_id)

    def test_get_user_returns_none_if_not_found(self, user_service, mock_user_repo):
        """Test get_user returns None if user not found."""
        user_id = uuid4()

        # Mock no user found
        mock_user_repo.find_by_id.return_value = None

        # Call get_user
        result = user_service.get_user(user_id)

        # Assertions
        assert result is None

        # Verify repository was called
        mock_user_repo.find_by_id.assert_called_once_with(user_id)

    def test_get_user_details_returns_details(
        self, user_service, mock_user_details_repo
    ):
        """Test get_user_details returns user details."""
        user_id = uuid4()

        # Mock user details
        mock_details = UserDetails()
        mock_details.id = uuid4()
        mock_details.user_id = user_id
        mock_details.first_name = "John"
        mock_details.last_name = "Doe"
        mock_details.phone = "+1234567890"
        mock_user_details_repo.find_by_user_id.return_value = mock_details

        # Call get_user_details
        result = user_service.get_user_details(user_id)

        # Assertions
        assert result is not None
        assert result.user_id == user_id
        assert result.first_name == "John"
        assert result.last_name == "Doe"

        # Verify repository was called
        mock_user_details_repo.find_by_user_id.assert_called_once_with(user_id)

    def test_get_user_details_returns_none_if_not_found(
        self, user_service, mock_user_details_repo
    ):
        """Test get_user_details returns None if details not found."""
        user_id = uuid4()

        # Mock no details found
        mock_user_details_repo.find_by_user_id.return_value = None

        # Call get_user_details
        result = user_service.get_user_details(user_id)

        # Assertions
        assert result is None

        # Verify repository was called
        mock_user_details_repo.find_by_user_id.assert_called_once_with(user_id)

    def test_update_user_details_updates_existing_details(
        self, user_service, mock_user_details_repo
    ):
        """Test update_user_details updates existing details."""
        user_id = uuid4()
        details_data = {
            "first_name": "Jane",
            "last_name": "Smith",
            "phone": "+9876543210",
        }

        # Mock existing details
        mock_details = UserDetails()
        mock_details.id = uuid4()
        mock_details.user_id = user_id
        mock_details.first_name = "John"
        mock_details.last_name = "Doe"
        mock_user_details_repo.find_by_user_id.return_value = mock_details

        # Mock update to return the updated object
        mock_user_details_repo.update.return_value = mock_details

        # Call update_user_details
        result = user_service.update_user_details(user_id, details_data)

        # Assertions
        assert result is not None
        assert result.user_id == user_id
        assert result.first_name == "Jane"
        assert result.last_name == "Smith"
        assert result.phone == "+9876543210"

        # Verify repository was called
        mock_user_details_repo.find_by_user_id.assert_called_once_with(user_id)
        mock_user_details_repo.update.assert_called_once_with(mock_details)

    def test_update_user_details_creates_if_not_exists(
        self, user_service, mock_user_details_repo
    ):
        """Test update_user_details creates details if not exists."""
        user_id = uuid4()
        details_data = {
            "first_name": "Jane",
            "last_name": "Smith",
            "phone": "+9876543210",
        }

        # Mock no existing details
        mock_user_details_repo.find_by_user_id.return_value = None

        # Mock created details
        created_details = UserDetails()
        created_details.id = uuid4()
        created_details.user_id = user_id
        created_details.first_name = "Jane"
        created_details.last_name = "Smith"
        created_details.phone = "+9876543210"
        mock_user_details_repo.save.return_value = created_details

        # Call update_user_details
        result = user_service.update_user_details(user_id, details_data)

        # Assertions
        assert result is not None
        assert result.user_id == user_id
        assert result.first_name == "Jane"
        assert result.last_name == "Smith"

        # Verify repository was called
        mock_user_details_repo.find_by_user_id.assert_called_once_with(user_id)
        mock_user_details_repo.save.assert_called_once()

        # Verify create was called with proper UserDetails object
        save_call_args = mock_user_details_repo.save.call_args[0][0]
        assert isinstance(save_call_args, UserDetails)
        assert save_call_args.user_id == user_id
        assert save_call_args.first_name == "Jane"

    def test_update_user_status_changes_status(self, user_service, mock_user_repo):
        """Test update_user_status changes user status."""
        user_id = uuid4()
        new_status = UserStatus.SUSPENDED

        # Mock existing user
        mock_user = User()
        mock_user.id = user_id
        mock_user.email = "test@example.com"
        mock_user.status = UserStatus.ACTIVE
        mock_user_repo.find_by_id.return_value = mock_user

        # Mock update to return the updated user
        mock_user_repo.update.return_value = mock_user

        # Call update_user_status
        result = user_service.update_user_status(user_id, new_status)

        # Assertions
        assert result is not None
        assert result.id == user_id
        assert result.status == UserStatus.SUSPENDED

        # Verify repository was called
        mock_user_repo.find_by_id.assert_called_once_with(user_id)
        mock_user_repo.update.assert_called_once_with(mock_user)

    def test_update_user_status_returns_none_if_user_not_found(
        self, user_service, mock_user_repo
    ):
        """Test update_user_status returns None if user not found."""
        user_id = uuid4()
        new_status = UserStatus.SUSPENDED

        # Mock no user found
        mock_user_repo.find_by_id.return_value = None

        # Call update_user_status
        result = user_service.update_user_status(user_id, new_status)

        # Assertions
        assert result is None

        # Verify update was NOT called
        mock_user_repo.update.assert_not_called()

    def test_update_user_details_validates_data(
        self, user_service, mock_user_details_repo
    ):
        """Test update_user_details validates input data."""
        user_id = uuid4()

        # Mock no existing details
        mock_user_details_repo.find_by_user_id.return_value = None

        # Test with empty dict
        result = user_service.update_user_details(user_id, {})
        assert result is not None  # Should still create empty details

        # Verify create was called
        mock_user_details_repo.save.assert_called_once()

    def test_update_user_details_handles_partial_updates(
        self, user_service, mock_user_details_repo
    ):
        """Test update_user_details handles partial field updates."""
        user_id = uuid4()
        details_data = {
            "first_name": "UpdatedName"
            # Only updating first_name, not other fields
        }

        # Mock existing details
        mock_details = UserDetails()
        mock_details.id = uuid4()
        mock_details.user_id = user_id
        mock_details.first_name = "Original"
        mock_details.last_name = "Doe"
        mock_details.phone = "+1234567890"
        mock_user_details_repo.find_by_user_id.return_value = mock_details

        # Mock update to return the updated object
        mock_user_details_repo.update.return_value = mock_details

        # Call update_user_details
        result = user_service.update_user_details(user_id, details_data)

        # Assertions
        assert result is not None
        assert result.first_name == "UpdatedName"
        assert result.last_name == "Doe"  # Should remain unchanged
        assert result.phone == "+1234567890"  # Should remain unchanged

        # Verify repository was called
        mock_user_details_repo.update.assert_called_once_with(mock_details)
