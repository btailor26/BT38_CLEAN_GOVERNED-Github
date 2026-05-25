"""
BT38 routes.py compatibility shell.

Single authority rule:
- governed_routes.py owns login, dashboard, settings, users, permissions, and runtime.
- This legacy blueprint remains empty only so app imports/registration do not break.
- Do not add user, settings, sync, warehouse, marketplace, or permission routes here.
"""

from flask import Blueprint

bp = Blueprint("routes", __name__)
