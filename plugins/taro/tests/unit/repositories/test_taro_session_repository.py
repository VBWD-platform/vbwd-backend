"""Tests for TaroSessionRepository."""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from plugins.taro.src.models.taro_session import TaroSession
from plugins.taro.src.repositories.taro_session_repository import TaroSessionRepository
from plugins.taro.src.enums import TaroSessionStatus


@pytest.fixture
def session_repo(db):
    """Fixture providing TaroSessionRepository instance."""
    return TaroSessionRepository(db.session)


@pytest.fixture
def sample_sessions(db):
    """Fixture creating sample TaroSession records."""
    user_id = str(uuid4())
    user_id_2 = str(uuid4())

    # Active session
    active_session = TaroSession(
        user_id=user_id,
        status=TaroSessionStatus.ACTIVE.value,
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        spread_id="spread-001",
        tokens_consumed=10,
        follow_up_count=0,
        max_follow_ups=3,
    )

    # Expired session
    expired_session = TaroSession(
        user_id=user_id,
        status=TaroSessionStatus.EXPIRED.value,
        started_at=datetime.utcnow() - timedelta(hours=1),
        expires_at=datetime.utcnow() - timedelta(minutes=30),
        spread_id="spread-002",
        tokens_consumed=15,
        follow_up_count=2,
        max_follow_ups=3,
    )

    # Closed session
    closed_session = TaroSession(
        user_id=user_id,
        status=TaroSessionStatus.CLOSED.value,
        started_at=datetime.utcnow() - timedelta(hours=2),
        expires_at=datetime.utcnow() - timedelta(hours=1, minutes=30),
        ended_at=datetime.utcnow() - timedelta(hours=1, minutes=45),
        spread_id="spread-003",
        tokens_consumed=20,
        follow_up_count=3,
        max_follow_ups=3,
    )

    # Another user's active session
    other_user_session = TaroSession(
        user_id=user_id_2,
        status=TaroSessionStatus.ACTIVE.value,
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        spread_id="spread-004",
        tokens_consumed=10,
        follow_up_count=0,
        max_follow_ups=0,
    )

    db.session.add_all(
        [active_session, expired_session, closed_session, other_user_session]
    )
    db.session.commit()

    return {
        "user_id": user_id,
        "user_id_2": user_id_2,
        "active": active_session,
        "expired": expired_session,
        "closed": closed_session,
        "other_user": other_user_session,
    }


class TestTaroSessionRepository:
    """Test TaroSessionRepository methods."""

    def test_create_session(self, session_repo, db):
        """Test creating a new TaroSession."""
        user_id = str(uuid4())
        expires_at = datetime.utcnow() + timedelta(minutes=30)

        result = session_repo.create(
            user_id=user_id,
            status=TaroSessionStatus.ACTIVE.value,
            started_at=datetime.utcnow(),
            expires_at=expires_at,
            spread_id="spread-new",
            tokens_consumed=10,
        )

        assert result.id is not None
        assert str(result.user_id) == user_id
        assert result.spread_id == "spread-new"

    def test_get_session_by_id(self, session_repo, sample_sessions):
        """Test retrieving TaroSession by ID."""
        session = sample_sessions["active"]
        result = session_repo.get_by_id(str(session.id))

        assert result is not None
        assert result.id == session.id
        assert result.user_id == session.user_id

    def test_get_session_by_id_not_found(self, session_repo):
        """Test retrieving non-existent session returns None."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        result = session_repo.get_by_id(fake_id)

        assert result is None

    def test_get_user_sessions(self, session_repo, sample_sessions):
        """Test retrieving all sessions for a user."""
        user_id = sample_sessions["user_id"]
        results = session_repo.get_user_sessions(user_id)

        assert len(results) == 3  # active, expired, closed
        assert all(str(s.user_id) == user_id for s in results)

    def test_get_user_sessions_empty(self, session_repo):
        """Test retrieving sessions for user with no sessions."""
        fake_user_id = str(uuid4())
        results = session_repo.get_user_sessions(fake_user_id)

        assert len(results) == 0

    def test_get_active_session(self, session_repo, sample_sessions):
        """Test retrieving active session for user."""
        user_id = sample_sessions["user_id"]
        result = session_repo.get_active_session(user_id)

        assert result is not None
        assert result.status == TaroSessionStatus.ACTIVE.value
        assert str(result.user_id) == user_id

    def test_get_active_session_none_exist(self, session_repo, sample_sessions):
        """Test getting active session when none exist."""
        # user_id_2 has an active session, but let's check a non-existent user
        fake_user_id = str(uuid4())
        result = session_repo.get_active_session(fake_user_id)

        assert result is None

    def test_get_active_session_only_returns_active(
        self, session_repo, sample_sessions
    ):
        """Test that get_active_session only returns ACTIVE status."""
        # user has active, expired, and closed sessions
        # get_active_session should only return the ACTIVE one
        user_id = sample_sessions["user_id"]
        result = session_repo.get_active_session(user_id)

        assert result.status == TaroSessionStatus.ACTIVE.value
        assert result.spread_id == "spread-001"

    def test_update_session_status(self, session_repo, sample_sessions):
        """Test updating session status."""
        session = sample_sessions["active"]
        session_repo.update_status(str(session.id), TaroSessionStatus.CLOSED)

        updated = session_repo.get_by_id(str(session.id))
        assert updated.status == TaroSessionStatus.CLOSED.value

    def test_update_session_status_not_found(self, session_repo):
        """Test updating status of non-existent session."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        # Should not raise error, just do nothing
        session_repo.update_status(fake_id, TaroSessionStatus.EXPIRED)

    def test_get_expired_sessions(self, session_repo, sample_sessions):
        """Test retrieving all expired sessions."""
        now = datetime.utcnow()
        results = session_repo.get_expired_sessions(before=now)

        # Should include expired and closed sessions from before now
        assert len(results) >= 2
        for session in results:
            assert session.expires_at < now

    def test_get_expired_sessions_with_status_filter(
        self, session_repo, sample_sessions
    ):
        """Test getting only EXPIRED status sessions (not CLOSED)."""
        now = datetime.utcnow()
        results = session_repo.get_expired_sessions(
            before=now, status_only=TaroSessionStatus.EXPIRED
        )

        # Should only include EXPIRED, not CLOSED
        assert len(results) >= 1
        assert all(s.status == TaroSessionStatus.EXPIRED.value for s in results)

    def test_delete_session(self, session_repo, sample_sessions):
        """Test deleting a session."""
        session = sample_sessions["active"]
        session_repo.delete(str(session.id))

        result = session_repo.get_by_id(str(session.id))
        assert result is None

    def test_delete_session_not_found(self, session_repo):
        """Test deleting non-existent session."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        # Should not raise error
        session_repo.delete(fake_id)

    def test_get_sessions_by_status(self, session_repo, sample_sessions):
        """Test retrieving sessions by status."""
        active_results = session_repo.get_sessions_by_status(TaroSessionStatus.ACTIVE)
        assert len(active_results) >= 2  # At least the two ACTIVE ones

        expired_results = session_repo.get_sessions_by_status(TaroSessionStatus.EXPIRED)
        assert len(expired_results) >= 1

    def test_user_session_count(self, session_repo, sample_sessions):
        """Test counting sessions for a user."""
        user_id = sample_sessions["user_id"]
        count = session_repo.count_user_sessions(user_id)

        assert count == 3

    def test_user_active_session_count(self, session_repo, sample_sessions):
        """Test counting active sessions for a user."""
        user_id = sample_sessions["user_id"]
        count = session_repo.count_active_sessions(user_id)

        assert count == 1
