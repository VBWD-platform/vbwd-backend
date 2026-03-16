"""Tests for TaroSession model."""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from plugins.taro.src.models.taro_session import TaroSession
from plugins.taro.src.enums import TaroSessionStatus


class TestTaroSessionCreation:
    """Test TaroSession model creation and validation."""

    def test_taro_session_creation(self, db):
        """Test creating a TaroSession with all fields."""
        user_id = str(uuid4())
        expires_at = datetime.utcnow() + timedelta(minutes=30)

        session = TaroSession(
            user_id=user_id,
            status=TaroSessionStatus.ACTIVE.value,
            spread_id="spread-001",
            expires_at=expires_at,
            tokens_consumed=10,
            follow_up_count=0,
            max_follow_ups=3,
        )

        assert session.user_id == user_id
        assert session.status == TaroSessionStatus.ACTIVE.value
        assert session.spread_id == "spread-001"
        assert session.expires_at == expires_at
        assert session.tokens_consumed == 10
        assert session.follow_up_count == 0
        assert session.max_follow_ups == 3
        assert session.ended_at is None

    def test_taro_session_requires_user_id(self, db):
        """Test that TaroSession requires a user_id at database level."""
        from sqlalchemy.exc import IntegrityError

        expires_at = datetime.utcnow() + timedelta(minutes=30)

        # SQLAlchemy doesn't raise TypeError on instantiation, but on commit
        session = TaroSession(
            status=TaroSessionStatus.ACTIVE.value,
            spread_id="spread-001",
            expires_at=expires_at,
            tokens_consumed=10,
        )
        # user_id is required so trying to add will fail
        db.session.add(session)
        with pytest.raises(IntegrityError):
            db.session.commit()

    def test_taro_session_default_status_is_active(self, db):
        """Test that default status is ACTIVE."""
        session = TaroSession(
            user_id=str(uuid4()),
            spread_id="spread-001",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        db.session.add(session)
        db.session.commit()

        # After persisting, default status should be ACTIVE
        assert session.status == TaroSessionStatus.ACTIVE.value

    def test_taro_session_status_transitions(self, db):
        """Test session status transitions."""
        session = TaroSession(
            user_id=str(uuid4()),
            spread_id="spread-001",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        db.session.add(session)
        db.session.commit()

        # Start as ACTIVE (set by default at database level)
        assert session.status == TaroSessionStatus.ACTIVE.value

        # Can be changed to EXPIRED
        session.status = TaroSessionStatus.EXPIRED.value
        assert session.status == TaroSessionStatus.EXPIRED.value

        # Can be changed to CLOSED
        session.status = TaroSessionStatus.CLOSED.value
        assert session.status == TaroSessionStatus.CLOSED.value

    def test_taro_session_expiry_calculation(self):
        """Test that expiry is 30 minutes from now."""
        now = datetime.utcnow()
        expires_at = now + timedelta(minutes=30)

        session = TaroSession(
            user_id=str(uuid4()), spread_id="spread-001", expires_at=expires_at
        )

        # Should be approximately 30 minutes from now
        diff = (session.expires_at - now).total_seconds()
        assert 29 * 60 <= diff <= 31 * 60  # Allow 1 minute variance

    def test_taro_session_token_consumption_tracking(self):
        """Test tracking tokens consumed."""
        session = TaroSession(
            user_id=str(uuid4()),
            spread_id="spread-001",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            tokens_consumed=15,
        )

        assert session.tokens_consumed == 15

        # Can be updated
        session.tokens_consumed = 25
        assert session.tokens_consumed == 25

    def test_taro_session_follow_up_count(self):
        """Test tracking follow-up questions."""
        session = TaroSession(
            user_id=str(uuid4()),
            spread_id="spread-001",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            follow_up_count=0,
            max_follow_ups=3,
        )

        assert session.follow_up_count == 0
        assert session.max_follow_ups == 3

        # Can increment
        session.follow_up_count = 1
        assert session.follow_up_count == 1

    def test_taro_session_max_follow_ups_from_addon(self):
        """Test that max_follow_ups can be set per plan."""
        # Basic plan: 0 follow-ups (only initial spread)
        session_basic = TaroSession(
            user_id=str(uuid4()),
            spread_id="spread-001",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            max_follow_ups=0,
        )
        assert session_basic.max_follow_ups == 0

        # Star plan: 3 follow-ups
        session_star = TaroSession(
            user_id=str(uuid4()),
            spread_id="spread-002",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            max_follow_ups=3,
        )
        assert session_star.max_follow_ups == 3

        # Guru plan: unlimited (represented as 12)
        session_guru = TaroSession(
            user_id="user-789",
            spread_id="spread-003",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            max_follow_ups=12,
        )
        assert session_guru.max_follow_ups == 12

    def test_taro_session_ended_at_nullable(self):
        """Test that ended_at is nullable until session ends."""
        session = TaroSession(
            user_id=str(uuid4()),
            spread_id="spread-001",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )

        assert session.ended_at is None

        # Can be set when closed
        session.status = TaroSessionStatus.CLOSED
        session.ended_at = datetime.utcnow()
        assert session.ended_at is not None

    def test_taro_session_timestamps(self, db):
        """Test that created_at and updated_at are set."""
        session = TaroSession(
            user_id=str(uuid4()),
            spread_id="spread-001",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        db.session.add(session)
        db.session.commit()

        assert session.created_at is not None
        assert session.updated_at is not None

    def test_taro_session_started_at(self, db):
        """Test that started_at is set."""
        session = TaroSession(
            user_id=str(uuid4()),
            spread_id="spread-001",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        db.session.add(session)
        db.session.commit()

        assert session.started_at is not None

    def test_taro_session_to_dict(self, db):
        """Test TaroSession.to_dict() method."""
        user_id = str(uuid4())
        expires_at = datetime.utcnow() + timedelta(minutes=30)
        session = TaroSession(
            user_id=user_id,
            spread_id="spread-001",
            expires_at=expires_at,
            tokens_consumed=15,
            follow_up_count=1,
            max_follow_ups=3,
        )
        db.session.add(session)
        db.session.commit()

        result = session.to_dict()

        assert result["user_id"] == user_id
        assert result["spread_id"] == "spread-001"
        assert result["status"] == TaroSessionStatus.ACTIVE.value
        assert result["tokens_consumed"] == 15
        assert result["follow_up_count"] == 1
        assert result["max_follow_ups"] == 3

    def test_taro_session_id_is_uuid(self, db):
        """Test that TaroSession gets a UUID id on creation."""
        from uuid import UUID

        session = TaroSession(
            user_id=str(uuid4()),
            spread_id="spread-001",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        db.session.add(session)
        db.session.commit()

        # ID should be set automatically by BaseModel
        assert session.id is not None
        assert isinstance(session.id, UUID)
