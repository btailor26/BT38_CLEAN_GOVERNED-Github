from datetime import datetime

from extensions import db


class RoyalMailConnection(db.Model):
    """Merchant-owned Royal Mail Click & Drop API connection.

    Royal Mail's public Click & Drop API authenticates with an account-specific
    API auth key. BT38 stores only encrypted key material; the merchant's normal
    Royal Mail website password is never collected or persisted here.
    """

    __tablename__ = "royal_mail_connections"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    account_email = db.Column(db.String(255), nullable=True)
    api_key_ciphertext = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="pending_validation", index=True)
    last_error = db.Column(db.Text, nullable=True)
    validated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_public_dict(self) -> dict:
        return {
            "connected": self.status == "connected",
            "status": self.status,
            "account_email": self.account_email,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
            "last_error": self.last_error,
        }
