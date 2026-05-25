"""
BT38 routes.py compatibility shell.

Runtime route instructions now live in governed_routes.py.
This module intentionally keeps legacy endpoint names that existing templates
already reference, while routing user access through one admin/fuse-box authority.
"""

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import User


bp = Blueprint("routes", __name__)


USER_PERMISSION_SECTIONS = [
    "inventory",
    "warehouse",
    "stores",
    "suppliers",
    "purchase_orders",
    "sync",
    "settings",
    "users",
]


def admin_required(f):
    """Single owner/admin gate for user authority assignment."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("governed.login"))
        if current_user.role != "admin":
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for("governed.governed_dashboard_page"))
        return f(*args, **kwargs)
    return decorated_function


def _build_user_permissions_from_form(form):
    """Build the existing permissions JSON from one authority form.

    These are shortcuts/authority flags only. They do not create duplicate sync,
    push, import, marketplace, or runtime paths.
    """
    permissions = {}
    for section in USER_PERMISSION_SECTIONS:
        permissions[f"view_{section}"] = form.get(f"view_{section}") == "on"
        permissions[f"edit_{section}"] = form.get(f"edit_{section}") == "on"

    # Runtime action shortcuts use the same single permissions JSON authority.
    # They do not create extra sync settings or alternate execution routes.
    permissions["can_push"] = permissions.get("edit_inventory", False) or permissions.get("edit_warehouse", False)
    permissions["can_sync"] = permissions.get("edit_sync", False)
    permissions["can_import"] = permissions.get("edit_stores", False)
    permissions["can_manage_users"] = permissions.get("edit_users", False)
    return permissions


@bp.route("/settings")
@login_required
def settings():
    """Compatibility endpoint used by existing templates."""
    return redirect(url_for("governed.governed_settings_page"))


@bp.route("/users")
@login_required
@admin_required
def user_management():
    users = User.query.order_by(User.created_at.desc(), User.id.desc()).all()
    return render_template("user_management.html", users=users)


@bp.route("/users/create", methods=["GET", "POST"])
@login_required
@admin_required
def create_user():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        role = (request.form.get("role") or "viewer").strip().lower()

        if role not in {"viewer", "manager", "admin"}:
            role = "viewer"

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("create_user.html")

        existing = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing:
            flash("A user with that username or email already exists.", "danger")
            return render_template("create_user.html")

        user = User(username=username, email=email, role=role, permissions={})
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("User created. You can now assign access from the edit screen.", "success")
        return redirect(url_for("routes.edit_user", user_id=user.id))

    return render_template("create_user.html")


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        role = (request.form.get("role") or "viewer").strip().lower()
        password = request.form.get("password") or ""

        if role not in {"viewer", "manager", "admin"}:
            role = "viewer"

        duplicate = User.query.filter(User.email == email, User.id != user.id).first()
        if duplicate:
            flash("Another user already uses that email.", "danger")
            return render_template("edit_user.html", user=user)

        user.email = email
        user.role = role
        user.is_active = request.form.get("is_active") == "on"
        user.permissions = _build_user_permissions_from_form(request.form)

        if password:
            if len(password) < 6:
                flash("Password must be at least 6 characters.", "danger")
                return render_template("edit_user.html", user=user)
            user.set_password(password)

        db.session.commit()
        flash("User access updated through the fuse-box permission authority.", "success")
        return redirect(url_for("routes.user_management"))

    if user.permissions is None:
        user.permissions = {}
    return render_template("edit_user.html", user=user)


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for("routes.user_management"))

    user.is_active = False
    db.session.commit()
    flash("User deactivated.", "success")
    return redirect(url_for("routes.user_management"))
