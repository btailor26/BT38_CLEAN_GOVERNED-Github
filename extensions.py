"""Shared Flask extensions to avoid circular imports"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

# Create shared instances
db = SQLAlchemy(model_class=Base)
login_manager = LoginManager()
