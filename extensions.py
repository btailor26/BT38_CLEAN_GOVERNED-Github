"""Shared Flask extensions to avoid circular imports."""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class BT38SQLAlchemy(SQLAlchemy):
    """Keep exact Amazon FBM profile persistence on the existing webhook path."""

    def init_app(self, app):
        super().init_app(app)
        # This is only an installer for the existing current-event alignment.
        # It adds no worker, poller, recovery scan or marketplace read. Amazon
        # Prime/program/promise facts are persisted from the webhook already
        # being processed by the governed runtime.
        from services.governed_amazon_fbm_profile_event_alignment import (
            install_governed_amazon_fbm_profile_event_alignment,
        )

        install_governed_amazon_fbm_profile_event_alignment(app)


class BT38LoginManager(LoginManager):
    """Keep authenticated BT38 browser sessions alive for four hours."""

    def init_app(self, app, add_context_processor=True):
        # app.py historically sets the permanent session to 30 minutes before
        # Flask-Login is initialised. Authentication owns the effective browser
        # session lifetime, so align that existing setting here without adding
        # another timer, refresh loop or authentication path.
        app.config["SESSION_PERMANENT"] = True
        app.config["PERMANENT_SESSION_LIFETIME"] = 4 * 60 * 60
        super().init_app(app, add_context_processor=add_context_processor)


# Create shared instances.
db = BT38SQLAlchemy(model_class=Base)
login_manager = BT38LoginManager()
