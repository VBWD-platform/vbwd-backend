"""Feature usage tracking model."""
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class FeatureUsage(BaseModel):
    """
    Feature usage tracking for tariff-based limits.

    Tracks how many times a user has used a feature
    within a billing period.
    """

    __tablename__ = "vbwd_feature_usage"

    user_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("vbwd_user.id"), nullable=False, index=True
    )
    feature_name = db.Column(db.String(100), nullable=False, index=True)
    usage_count = db.Column(db.Integer, default=0, nullable=False)
    period_start = db.Column(db.DateTime, nullable=False, index=True)

    # Unique constraint: one record per user/feature/period
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "feature_name", "period_start", name="uq_user_feature_period"
        ),
    )

    # Relationship
    user = db.relationship("User", backref=db.backref("feature_usages", lazy="dynamic"))

    def increment(self, amount: int = 1) -> int:
        """
        Increment usage count.

        Args:
            amount: Amount to increment (default 1)

        Returns:
            New usage count
        """
        self.usage_count += amount
        return self.usage_count

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "feature_name": self.feature_name,
            "usage_count": self.usage_count,
            "period_start": self.period_start.isoformat()
            if self.period_start
            else None,
        }

    def __repr__(self) -> str:
        return f"<FeatureUsage(user={self.user_id}, feature='{self.feature_name}', count={self.usage_count})>"
