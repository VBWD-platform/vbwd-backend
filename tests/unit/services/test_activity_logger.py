"""S17 — activity_logger service contract tests.

ActivityLogger is a concrete service (not a port). Tests cover the
logging side-effect + the action+metadata payload shape.
"""
import logging

from vbwd.services.activity_logger import ActivityLogger


def test_log_records_action_via_logger(caplog):
    activity_logger = ActivityLogger()
    with caplog.at_level(logging.INFO):
        activity_logger.log(action="user.login", user_id="user-1")
    assert any("user.login" in record.message for record in caplog.records)


def test_log_includes_user_id_in_log_extra(caplog):
    """user_id is passed via the LogRecord's ``extra`` payload, not into
    the message string — assert it lands on the record itself."""
    activity_logger = ActivityLogger()
    with caplog.at_level(logging.INFO):
        activity_logger.log(action="user.created", user_id="user-42")
    record = next(record for record in caplog.records if record.levelno == logging.INFO)
    assert getattr(record, "user_id", None) == "user-42"


def test_log_with_metadata_includes_it_in_record_extra(caplog):
    activity_logger = ActivityLogger()
    with caplog.at_level(logging.INFO):
        activity_logger.log(
            action="password_reset_requested",
            user_id="user-1",
            metadata={"ip": "10.0.0.1"},
        )
    record = next(record for record in caplog.records if record.levelno == logging.INFO)
    assert getattr(record, "metadata", None) == {"ip": "10.0.0.1"}


def test_log_without_user_id_does_not_raise(caplog):
    """Failure-path logging often lacks a user_id (e.g. token unknown)."""
    activity_logger = ActivityLogger()
    with caplog.at_level(logging.INFO):
        activity_logger.log(
            action="password_reset_failed",
            metadata={"reason": "bad_token", "ip": "10.0.0.1"},
        )
    # No assertion on exact format — just that it didn't blow up.


def test_log_with_no_metadata_emits_record(caplog):
    activity_logger = ActivityLogger()
    with caplog.at_level(logging.INFO):
        activity_logger.log(action="user.logout", user_id="user-1")
    assert caplog.records  # something was logged
