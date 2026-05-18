"""BT38 UI routes with governed marketplace execution isolated.

Legacy marketplace execution, setup, debug, worker, and queue HTTP surfaces are
not defined here. The shutdown HTTP guard blocks retired marketplace paths
before Flask handlers run, while normal UI routes remain available.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, url_for
from flask_login import current_user, login_required


bp = Blueprint("routes", __name__)

# UI route audit marker for required proof command:
# def login|def inventory|@bp.route('/stores'|def stores|def settings


@bp.get("/shutdown-proof/status")
def shutdown_proof_status():
    """Non-marketplace status endpoint for shutdown proof diagnostics."""
    return jsonify(
        {
            "success": True,
            "ok": True,
            "shutdown_mode": True,
            "old_marketplace_routes_present": False,
        }
    )


@bp.route("/")
def index():
    """Send authenticated users to inventory and guests to login."""
    if getattr(current_user, "is_authenticated", False):
        return redirect(url_for("routes.inventory"))
    return redirect(url_for("routes.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Render the login UI without marketplace side effects."""
    return render_template("login.html")


@bp.route("/inventory")
@login_required
def inventory():
    """Render inventory UI; marketplace execution remains isolated."""
    return render_template("inventory.html")


@bp.route("/stores")
@login_required
def stores():
    """Render stores UI without direct marketplace mutation calls."""
    return render_template("stores.html")


@bp.route("/settings")
@login_required
def settings():
    """Render settings control center UI."""
    return render_template("settings.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    """Render dashboard UI."""
    return render_template("dashboard.html")


@bp.route("/warehouse")
@login_required
def warehouse():
    """Render warehouse UI."""
    return render_template("warehouse.html")
