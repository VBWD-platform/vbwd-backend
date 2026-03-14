"""Activity logging service for audit trail."""
import logging
from typing import Any, Dict, Optional
from src.utils.datetime_utils import utcnow

logger = logging.getLogger(__name__)


class ActivityLogger:
    """
    Service for logging user and system activities.

    Provides audit trail for security-sensitive operations.
    """

    def __init__(self, log_to_db: bool = False):
        """
        Initialize activity logger.

        Args:
            log_to_db: Whether to also log to database (future feature)
        """
        self._log_to_db = log_to_db

    def log(
        self,
        action: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log an activity.

        Args:
            action: Action identifier (e.g., "password_reset_requested")
            user_id: Optional user ID associated with the action
            metadata: Optional additional data to log
        """
        log_entry = {
            "timestamp": utcnow().isoformat(),
            "action": action,
            "user_id": user_id,
            "metadata": metadata or {},
        }

        # Log to standard logger
        logger.info(f"Activity: {action}", extra=log_entry)

        # Future: Log to database for queryable audit trail
        if self._log_to_db:
            self._persist_to_db(log_entry)

    def _persist_to_db(self, log_entry: Dict[str, Any]) -> None:
        """
        Persist log entry to database.

        Args:
            log_entry: Log entry to persist

        Note: This is a placeholder for future database logging.
        """
        # TODO: Implement database logging when ActivityLog model is created
        pass

    def log_security_event(
        self,
        event_type: str,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log a security-related event.

        Args:
            event_type: Type of security event
            user_id: User ID if applicable
            ip_address: IP address of the request
            details: Additional event details
        """
        metadata = {"ip": ip_address, "event_type": event_type, **(details or {})}

        self.log(action=f"security.{event_type}", user_id=user_id, metadata=metadata)
