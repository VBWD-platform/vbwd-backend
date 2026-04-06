"""Unit tests for UserAccessLevelService (Sprint 17b)."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.services.user_access_level_service import UserAccessLevelService


@pytest.fixture()
def mock_session():
    return MagicMock()


@pytest.fixture()
def service(mock_session):
    return UserAccessLevelService(session=mock_session)


class TestFindBySlug:
    def test_returns_level_when_found(self, service, mock_session):
        expected_level = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            expected_level
        )

        result = service.find_by_slug("subscribed-basic")

        assert result is expected_level

    def test_returns_none_when_not_found(self, service, mock_session):
        mock_session.query.return_value.filter.return_value.first.return_value = (
            None
        )

        result = service.find_by_slug("nonexistent")

        assert result is None


class TestFindByLinkedPlanSlug:
    def test_returns_level_linked_to_plan(self, service, mock_session):
        expected_level = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            expected_level
        )

        result = service.find_by_linked_plan_slug("basic")

        assert result is expected_level


class TestAssign:
    def test_assigns_level_to_user(self, service, mock_session):
        user_id = uuid4()
        level_id = uuid4()

        user = MagicMock()
        user.assigned_user_access_levels = []

        level = MagicMock()
        level.id = level_id

        mock_session.get.side_effect = lambda model, uid: (
            user if uid == user_id else level
        )

        result = service.assign(user_id, level_id)

        assert result is True
        assert level in user.assigned_user_access_levels
        mock_session.flush.assert_called_once()

    def test_returns_false_when_already_assigned(self, service, mock_session):
        user_id = uuid4()
        level_id = uuid4()

        level = MagicMock()
        level.id = level_id

        user = MagicMock()
        user.assigned_user_access_levels = [level]

        mock_session.get.side_effect = lambda model, uid: (
            user if uid == user_id else level
        )

        result = service.assign(user_id, level_id)

        assert result is False

    def test_returns_false_when_user_not_found(self, service, mock_session):
        mock_session.get.return_value = None

        result = service.assign(uuid4(), uuid4())

        assert result is False

    def test_returns_false_when_level_not_found(self, service, mock_session):
        user_id = uuid4()
        user = MagicMock()
        mock_session.get.side_effect = lambda model, uid: (
            user if uid == user_id else None
        )

        result = service.assign(user_id, uuid4())

        assert result is False


class TestRevoke:
    def test_revokes_level_from_user(self, service, mock_session):
        user_id = uuid4()
        level_id = uuid4()

        level = MagicMock()
        level.id = level_id

        user = MagicMock()
        user.assigned_user_access_levels = [level]

        mock_session.get.side_effect = lambda model, uid: (
            user if uid == user_id else level
        )

        result = service.revoke(user_id, level_id)

        assert result is True
        assert level not in user.assigned_user_access_levels
        mock_session.flush.assert_called_once()

    def test_returns_false_when_not_assigned(self, service, mock_session):
        user_id = uuid4()
        level_id = uuid4()

        level = MagicMock()
        level.id = level_id

        user = MagicMock()
        user.assigned_user_access_levels = []

        mock_session.get.side_effect = lambda model, uid: (
            user if uid == user_id else level
        )

        result = service.revoke(user_id, level_id)

        assert result is False

    def test_returns_false_when_user_not_found(self, service, mock_session):
        mock_session.get.return_value = None

        result = service.revoke(uuid4(), uuid4())

        assert result is False


class TestRevokePlanLinkedLevels:
    def test_revokes_all_levels_for_plan(self, service, mock_session):
        user_id = uuid4()
        level1 = MagicMock()
        level1.id = uuid4()
        level2 = MagicMock()
        level2.id = uuid4()

        mock_session.query.return_value.filter.return_value.all.return_value = [
            level1,
            level2,
        ]

        user = MagicMock()
        user.assigned_user_access_levels = [level1, level2]
        mock_session.get.side_effect = lambda model, uid: (
            user if uid == user_id else (
                level1 if uid == level1.id else level2
            )
        )

        result = service.revoke_plan_linked_levels(user_id, "basic")

        assert result == 2
