"""EmailTemplate model — stores per-event HTML/text templates."""
from src.extensions import db
from src.models.base import BaseModel


class EmailTemplate(BaseModel):
    """One template per event_type (unique).

    Columns
    -------
    event_type  : machine key, e.g. "subscription.activated"
    subject     : Jinja2 string, e.g. "Welcome, {{ user_name }}!"
    html_body   : full HTML Jinja2 template
    text_body   : plain-text fallback Jinja2 template
    is_active   : False = skip sending for this event
    """

    __tablename__ = "email_template"

    event_type = db.Column(db.String(100), nullable=False, unique=True, index=True)
    subject = db.Column(db.String(255), nullable=False)
    html_body = db.Column(db.Text, nullable=False, default="")
    text_body = db.Column(db.Text, nullable=False, default="")
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "event_type": self.event_type,
            "subject": self.subject,
            "html_body": self.html_body,
            "text_body": self.text_body,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
