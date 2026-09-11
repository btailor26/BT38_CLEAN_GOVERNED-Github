"""Customer-owned profile, branding and team alignment for BT38.

This extends the existing User/permission authority; it does not create a second
authentication system.  A paying customer owns a small account/workspace layer,
can assign at most five users, and can replace product-shell BT38 branding with
their own business logo.  BT38 remains a quiet "Powered by BT38" attribution.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
import html
import json
import re
import secrets

from flask import Response, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import UniqueConstraint, func

from app import app
from extensions import db
from models import SystemLog, User


class CustomerAccount(db.Model):
    __tablename__ = "customer_accounts"

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
        index=True,
    )
    business_name = db.Column(db.String(180), nullable=True)
    logo_data = db.Column(db.LargeBinary, nullable=True)
    logo_mime = db.Column(db.String(40), nullable=True)
    plan_name = db.Column(db.String(80), nullable=False, default="BT38")
    billing_status = db.Column(db.String(30), nullable=False, default="setup_pending")
    user_limit = db.Column(db.Integer, nullable=False, default=5)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class CustomerAccountMember(db.Model):
    __tablename__ = "customer_account_members"
    __table_args__ = (
        UniqueConstraint("account_id", "user_id", name="uq_customer_account_member"),
        UniqueConstraint("user_id", name="uq_customer_account_member_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("customer_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    access_preset = db.Column(db.String(40), nullable=False, default="assistant")
    is_owner = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class UserProfile(db.Model):
    __tablename__ = "user_profiles"

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name = db.Column(db.String(140), nullable=True)
    position = db.Column(db.String(140), nullable=True)
    setup_required = db.Column(db.Boolean, nullable=False, default=False)
    setup_completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


# Existing app.py has already performed its safe create_all() before main.py
# imports alignment modules. Register these models and run the same idempotent
# create_all authority once more so the profile tables exist without a second
# migration engine.
with app.app_context():
    db.create_all()


_PERMISSION_SECTIONS = (
    "inventory",
    "warehouse",
    "stores",
    "suppliers",
    "purchase_orders",
    "sync",
    "settings",
    "users",
)


def _permission_map(*, view=(), edit=(), can_push=False, can_sync=False, can_import=False, manage_users=False):
    permissions = {}
    view_set = set(view)
    edit_set = set(edit)
    for section in _PERMISSION_SECTIONS:
        permissions[f"view_{section}"] = section in view_set or section in edit_set
        permissions[f"edit_{section}"] = section in edit_set
    permissions.update({
        "can_push": bool(can_push),
        "can_sync": bool(can_sync),
        "can_import": bool(can_import),
        "manage_users": bool(manage_users),
    })
    return permissions


ROLE_PRESETS = {
    "operations_manager": {
        "label": "Operations Manager",
        "description": "Runs day-to-day stock, stores, suppliers, purchasing and governed sync work.",
        "role": "manager",
        "permissions": _permission_map(
            view=("inventory", "warehouse", "stores", "suppliers", "purchase_orders", "sync", "settings"),
            edit=("inventory", "warehouse", "stores", "suppliers", "purchase_orders", "sync"),
            can_push=True,
            can_sync=True,
            can_import=True,
        ),
    },
    "warehouse_manager": {
        "label": "Warehouse Manager",
        "description": "Controls warehouse and stock work with visibility of orders, suppliers and stores.",
        "role": "manager",
        "permissions": _permission_map(
            view=("inventory", "warehouse", "stores", "suppliers", "purchase_orders"),
            edit=("inventory", "warehouse"),
        ),
    },
    "purchasing_manager": {
        "label": "Supplier / Purchasing",
        "description": "Manages suppliers and purchase orders while seeing the stock needed to buy well.",
        "role": "manager",
        "permissions": _permission_map(
            view=("inventory", "warehouse", "suppliers", "purchase_orders"),
            edit=("suppliers", "purchase_orders"),
        ),
    },
    "content_manager": {
        "label": "Content Manager",
        "description": "Works with product/listing content through the existing inventory and store permissions.",
        "role": "manager",
        "permissions": _permission_map(
            view=("inventory", "stores"),
            edit=("inventory",),
        ),
    },
    "assistant": {
        "label": "Assistant",
        "description": "Safe operational visibility without marketplace, sync or account-management authority.",
        "role": "viewer",
        "permissions": _permission_map(
            view=("inventory", "warehouse", "stores", "suppliers", "purchase_orders"),
        ),
    },
}


_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
_PROFILE_ALLOWED_PATHS = {
    "/login",
    "/logout",
    "/profile/first-login",
    "/profile/logo",
    "/forgot-password",
    "/reset-password",
}


def _load_log_details(row: SystemLog) -> dict:
    try:
        value = json.loads(row.details or "{}")
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _approved_application(email: str) -> dict | None:
    email = str(email or "").strip().lower()
    if not email:
        return None
    rows = (
        SystemLog.query
        .filter(SystemLog.log_type == "early_access_application")
        .order_by(SystemLog.created_at.desc(), SystemLog.id.desc())
        .limit(500)
        .all()
    )
    for row in rows:
        details = _load_log_details(row)
        if str(details.get("email") or "").strip().lower() != email:
            continue
        if str(details.get("status") or "").strip().lower() == "approved":
            return details
    return None


def _profile_for(user_id: int) -> UserProfile | None:
    return db.session.get(UserProfile, int(user_id))


def _membership_for(user_id: int) -> CustomerAccountMember | None:
    return CustomerAccountMember.query.filter_by(user_id=int(user_id)).first()


def _account_for_user(user_id: int) -> tuple[CustomerAccount | None, CustomerAccountMember | None]:
    member = _membership_for(user_id)
    if not member:
        return None, None
    return db.session.get(CustomerAccount, member.account_id), member


def _create_owner_account(user: User, *, business_name: str = "") -> CustomerAccount:
    existing, member = _account_for_user(user.id)
    if existing:
        return existing

    account = CustomerAccount(
        owner_user_id=user.id,
        business_name=str(business_name or "").strip()[:180] or None,
        plan_name="BT38",
        billing_status="setup_pending",
        user_limit=5,
    )
    db.session.add(account)
    db.session.flush()
    db.session.add(CustomerAccountMember(
        account_id=account.id,
        user_id=user.id,
        access_preset="owner",
        is_owner=True,
    ))
    return account


def _ensure_profile(user: User) -> UserProfile:
    profile = _profile_for(user.id)
    if profile:
        return profile

    approved = _approved_application(user.email)
    profile = UserProfile(
        user_id=user.id,
        display_name=(str(approved.get("full_name") or "").strip()[:140] if approved else str(user.username or "").strip()[:140]),
        position=None,
        setup_required=bool(approved),
        setup_completed_at=None if approved else datetime.utcnow(),
    )
    db.session.add(profile)

    if approved:
        _create_owner_account(
            user,
            business_name=str(approved.get("business_name") or "").strip(),
        )

    db.session.commit()
    return profile


def _ensure_legacy_admin_account(user: User) -> CustomerAccount | None:
    account, _ = _account_for_user(user.id)
    if account:
        return account
    # Existing live users are grandfathered and never forced through onboarding.
    # An existing admin only receives an account shell when they deliberately
    # enter Profile, preserving today's production login journey.
    if str(getattr(user, "role", "") or "") != "admin":
        return None
    account = _create_owner_account(user)
    db.session.commit()
    return account


def _member_count(account_id: int) -> int:
    return CustomerAccountMember.query.filter_by(account_id=int(account_id)).count()


def _display_name(user: User) -> str:
    profile = _profile_for(user.id)
    name = str(getattr(profile, "display_name", "") or "").strip()
    return name or str(user.username or user.email or "User")


def _first_name(user: User) -> str:
    return _display_name(user).split()[0]


def _is_owner(member: CustomerAccountMember | None) -> bool:
    return bool(member and member.is_owner)


def _unique_username(value: str, *, exclude_user_id: int | None = None) -> tuple[str, str]:
    username = str(value or "").strip().lower()
    if not _USERNAME_RE.fullmatch(username):
        return "", "Use 3–32 lowercase letters, numbers, dots, dashes or underscores."
    query = User.query.filter(func.lower(User.username) == username)
    if exclude_user_id is not None:
        query = query.filter(User.id != int(exclude_user_id))
    if query.first():
        return "", "That username is already in use. Choose another."
    return username, ""


def _apply_preset(user: User, preset_key: str) -> str:
    preset_key = str(preset_key or "").strip().lower()
    preset = ROLE_PRESETS.get(preset_key)
    if not preset:
        preset_key = "assistant"
        preset = ROLE_PRESETS[preset_key]
    user.role = preset["role"]
    user.permissions = dict(preset["permissions"])
    return preset_key


def _logo_kind(payload: bytes) -> str | None:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    return None


def _brand_context() -> dict:
    if not current_user.is_authenticated:
        return {
            "business_name": "BT38 Inventory",
            "logo_url": "",
            "is_customer_branded": False,
            "display_name": "",
            "position": "",
            "is_owner": False,
            "billing_visible": False,
        }
    profile = _profile_for(current_user.id)
    account, member = _account_for_user(current_user.id)
    logo_url = url_for("bt38_profile_logo") if account and account.logo_data else ""
    return {
        "business_name": str(account.business_name or "").strip() if account else "",
        "logo_url": logo_url,
        "is_customer_branded": bool(account and account.logo_data),
        "display_name": str(profile.display_name or "").strip() if profile else _display_name(current_user),
        "position": str(profile.position or "").strip() if profile else "",
        "is_owner": _is_owner(member),
        "billing_visible": _is_owner(member),
    }


@app.context_processor
def bt38_account_profile_context():
    return {
        "account_brand": _brand_context(),
        "account_role_presets": ROLE_PRESETS,
    }


@app.before_request
def bt38_first_login_profile_gate():
    if not current_user.is_authenticated:
        return None
    path = request.path.rstrip("/") or "/"
    if path.startswith("/static/") or path in _PROFILE_ALLOWED_PATHS:
        return None

    profile = _ensure_profile(current_user)
    if not profile.setup_required:
        return None

    if request.method == "GET":
        return redirect(url_for("bt38_profile_first_login"))
    return jsonify({
        "ok": False,
        "reason": "profile_setup_required",
        "message": "Complete your username, name and position before continuing.",
    }), 409


@app.route("/profile/first-login", methods=["GET", "POST"])
@login_required
def bt38_profile_first_login():
    profile = _ensure_profile(current_user)
    if not profile.setup_required:
        return redirect(url_for("governed.governed_dashboard_page"))

    if request.method == "GET":
        return render_template(
            "profile_first_login.html",
            profile=profile,
            suggested_username="",
        )

    username, username_error = _unique_username(
        request.form.get("username"),
        exclude_user_id=current_user.id,
    )
    display_name = str(request.form.get("display_name") or "").strip()[:140]
    position = str(request.form.get("position") or "").strip()[:140]
    error = username_error
    if not display_name:
        error = error or "Enter the name you want COFI and your team to use."
    if not position:
        error = error or "Enter your position."

    if error:
        return render_template(
            "profile_first_login.html",
            profile=profile,
            suggested_username=str(request.form.get("username") or ""),
            error=error,
            form=request.form,
        ), 400

    current_user.username = username
    profile.display_name = display_name
    profile.position = position
    profile.setup_required = False
    profile.setup_completed_at = datetime.utcnow()
    db.session.commit()

    session["bt38_cofi_first_welcome"] = display_name
    flash(f"Welcome, {display_name.split()[0]}. COFI is ready when you are.", "success")
    return redirect(url_for("governed.governed_dashboard_page"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def bt38_profile_page():
    profile = _ensure_profile(current_user)
    account, member = _account_for_user(current_user.id)
    if not account and str(current_user.role or "") == "admin":
        account = _ensure_legacy_admin_account(current_user)
        account, member = _account_for_user(current_user.id)

    if request.method == "POST":
        section = str(request.form.get("section") or "personal").strip().lower()

        if section == "personal":
            username, username_error = _unique_username(
                request.form.get("username"),
                exclude_user_id=current_user.id,
            )
            display_name = str(request.form.get("display_name") or "").strip()[:140]
            position = str(request.form.get("position") or "").strip()[:140]
            if username_error or not display_name or not position:
                flash(username_error or "Name and position are required.", "danger")
            else:
                current_user.username = username
                profile.display_name = display_name
                profile.position = position
                db.session.commit()
                flash("Your profile has been updated.", "success")
            return redirect(url_for("bt38_profile_page") + "#personal")

        if section == "business":
            if not account or not _is_owner(member):
                flash("Only the account owner can change business branding.", "danger")
                return redirect(url_for("bt38_profile_page") + "#business")

            business_name = str(request.form.get("business_name") or "").strip()[:180]
            if not business_name:
                flash("Enter your business name.", "danger")
                return redirect(url_for("bt38_profile_page") + "#business")

            logo = request.files.get("logo")
            if logo and logo.filename:
                payload = logo.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    flash("Logo must be 1 MB or smaller.", "danger")
                    return redirect(url_for("bt38_profile_page") + "#business")
                logo_mime = _logo_kind(payload)
                if not logo_mime:
                    flash("Use a PNG, JPEG or WebP logo.", "danger")
                    return redirect(url_for("bt38_profile_page") + "#business")
                account.logo_data = payload
                account.logo_mime = logo_mime

            account.business_name = business_name
            db.session.commit()
            flash("Business branding has been updated.", "success")
            return redirect(url_for("bt38_profile_page") + "#business")

        flash("That profile section could not be updated.", "danger")
        return redirect(url_for("bt38_profile_page"))

    team = []
    if account:
        memberships = (
            CustomerAccountMember.query
            .filter_by(account_id=account.id)
            .order_by(CustomerAccountMember.is_owner.desc(), CustomerAccountMember.id.asc())
            .all()
        )
        user_ids = [row.user_id for row in memberships]
        users = {
            user.id: user
            for user in User.query.filter(User.id.in_(user_ids)).all()
        } if user_ids else {}
        profiles = {
            row.user_id: row
            for row in UserProfile.query.filter(UserProfile.user_id.in_(user_ids)).all()
        } if user_ids else {}
        for membership in memberships:
            user = users.get(membership.user_id)
            if not user:
                continue
            user_profile = profiles.get(user.id)
            preset = ROLE_PRESETS.get(membership.access_preset, {})
            team.append({
                "membership": membership,
                "user": user,
                "profile": user_profile,
                "preset_label": "Owner" if membership.is_owner else preset.get("label", "Team member"),
            })

    return render_template(
        "profile.html",
        profile=profile,
        account=account,
        member=member,
        team=team,
        role_presets=ROLE_PRESETS,
        seat_count=_member_count(account.id) if account else 0,
    )


@app.post("/profile/team/add")
@login_required
def bt38_profile_team_add():
    _ensure_profile(current_user)
    account, member = _account_for_user(current_user.id)
    if not account or not _is_owner(member):
        flash("Only the paying account owner can add team members.", "danger")
        return redirect(url_for("bt38_profile_page") + "#team")

    if _member_count(account.id) >= int(account.user_limit or 5):
        flash(f"Your plan includes {int(account.user_limit or 5)} users and all seats are currently assigned.", "warning")
        return redirect(url_for("bt38_profile_page") + "#team")

    email = str(request.form.get("email") or "").strip().lower()[:120]
    preset_key = str(request.form.get("access_preset") or "assistant").strip().lower()
    if "@" not in email:
        flash("Enter a valid team member email.", "danger")
        return redirect(url_for("bt38_profile_page") + "#team")
    if preset_key not in ROLE_PRESETS:
        flash("Choose a valid team role.", "danger")
        return redirect(url_for("bt38_profile_page") + "#team")

    user = User.query.filter(func.lower(User.email) == email).first()
    if user:
        existing_member = _membership_for(user.id)
        if existing_member:
            if existing_member.account_id == account.id:
                flash("That user is already on your team.", "info")
            else:
                flash("That email already belongs to another customer account.", "danger")
            return redirect(url_for("bt38_profile_page") + "#team")
    else:
        placeholder = f"pending_{secrets.token_hex(10)}"
        user = User(
            username=placeholder,
            email=email,
            role="viewer",
            permissions={},
            is_active=True,
        )
        user.set_password(secrets.token_urlsafe(48))
        _apply_preset(user, preset_key)
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProfile(
            user_id=user.id,
            display_name=None,
            position=None,
            setup_required=True,
            setup_completed_at=None,
        ))

    db.session.add(CustomerAccountMember(
        account_id=account.id,
        user_id=user.id,
        access_preset=_apply_preset(user, preset_key),
        is_owner=False,
    ))
    db.session.commit()
    flash("Team member added. They can use Google sign-in with that email, then choose Username, Name and Position.", "success")
    return redirect(url_for("bt38_profile_page") + "#team")


@app.post("/profile/team/<int:user_id>/role")
@login_required
def bt38_profile_team_role(user_id: int):
    account, member = _account_for_user(current_user.id)
    if not account or not _is_owner(member):
        flash("Only the account owner can change team access.", "danger")
        return redirect(url_for("bt38_profile_page") + "#team")

    target_membership = CustomerAccountMember.query.filter_by(
        account_id=account.id,
        user_id=user_id,
    ).first()
    if not target_membership or target_membership.is_owner:
        flash("Owner access cannot be changed here.", "danger")
        return redirect(url_for("bt38_profile_page") + "#team")

    preset_key = str(request.form.get("access_preset") or "assistant").strip().lower()
    if preset_key not in ROLE_PRESETS:
        flash("Choose a valid team role.", "danger")
        return redirect(url_for("bt38_profile_page") + "#team")

    user = db.session.get(User, user_id)
    if not user:
        flash("Team member was not found.", "danger")
        return redirect(url_for("bt38_profile_page") + "#team")
    target_membership.access_preset = _apply_preset(user, preset_key)
    db.session.commit()
    flash("Team permissions updated.", "success")
    return redirect(url_for("bt38_profile_page") + "#team")


@app.post("/profile/team/<int:user_id>/remove")
@login_required
def bt38_profile_team_remove(user_id: int):
    account, member = _account_for_user(current_user.id)
    if not account or not _is_owner(member):
        flash("Only the account owner can remove team members.", "danger")
        return redirect(url_for("bt38_profile_page") + "#team")

    target_membership = CustomerAccountMember.query.filter_by(
        account_id=account.id,
        user_id=user_id,
    ).first()
    if not target_membership or target_membership.is_owner:
        flash("The account owner cannot be removed.", "danger")
        return redirect(url_for("bt38_profile_page") + "#team")

    user = db.session.get(User, user_id)
    if user:
        user.is_active = False
    db.session.delete(target_membership)
    db.session.commit()
    flash("Team member access has been removed.", "success")
    return redirect(url_for("bt38_profile_page") + "#team")


@app.get("/profile/logo")
@login_required
def bt38_profile_logo():
    account, _ = _account_for_user(current_user.id)
    if not account or not account.logo_data or not account.logo_mime:
        return Response(status=404)
    response = Response(bytes(account.logo_data), mimetype=account.logo_mime)
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


@app.get("/billing")
@login_required
def bt38_billing_page():
    _ensure_profile(current_user)
    account, member = _account_for_user(current_user.id)
    if not account or not _is_owner(member):
        flash("Billing is available to the paying account owner.", "warning")
        return redirect(url_for("bt38_profile_page"))
    return render_template(
        "billing.html",
        account=account,
        seat_count=_member_count(account.id),
    )


@app.after_request
def bt38_customer_owned_shell_alignment(response):
    """Align the existing shell to customer ownership without replacing base.html.

    The repository's shared shell predates customer accounts and hard-codes BT38
    in three visual positions.  Preserve that shell/layout and replace only those
    identity anchors for authenticated customer accounts.  This is deliberately
    narrow so marketplace UI/layout remains untouched.
    """
    if not current_user.is_authenticated:
        return response
    if response.status_code >= 400:
        return response
    if not response.content_type or "text/html" not in response.content_type:
        return response

    account, member = _account_for_user(current_user.id)
    profile = _profile_for(current_user.id)
    if not profile:
        return response

    body = response.get_data(as_text=True)
    if not body:
        return response

    display_name = html.escape(str(profile.display_name or current_user.username or "Profile"))
    position = html.escape(str(profile.position or ""))
    business_name = html.escape(str(account.business_name or "").strip()) if account else ""

    if account and account.logo_data:
        brand_label = business_name or display_name
        brand_markup = (
            f'<img src="{url_for("bt38_profile_logo")}" alt="{brand_label}" '
            'style="height:30px;max-width:150px;object-fit:contain;border-radius:5px" class="me-2">'
            f'<span>{brand_label}</span>'
        )
        body = body.replace(
            '<i data-feather="package" class="me-2"></i>BT38 Inventory',
            brand_markup,
        )
        body = body.replace(
            '<span class="text-muted small">BT38 Inventory Management</span>',
            f'<span class="text-muted small">{brand_label} <span class="ms-2">Powered by BT38</span></span>',
        )
    elif account and business_name:
        body = body.replace(
            '<i data-feather="package" class="me-2"></i>BT38 Inventory',
            f'<i data-feather="package" class="me-2"></i>{business_name}',
        )

    top_login = '''<a class="nav-link text-light" href="/login">
                    <i data-feather="log-in" class="me-1"></i>Login
                </a>'''
    billing_item = (
        '<li><a class="dropdown-item" href="/billing"><i data-feather="credit-card" class="me-2"></i>Billing</a></li>'
        if _is_owner(member) else ""
    )
    account_menu = f'''<div class="dropdown">
                    <button class="btn btn-dark border-0 dropdown-toggle d-flex align-items-center gap-2" type="button" data-bs-toggle="dropdown" aria-expanded="false">
                        <span class="rounded-circle bg-light text-dark d-inline-flex align-items-center justify-content-center" style="width:30px;height:30px;font-weight:700">{html.escape(display_name[:1].upper())}</span>
                        <span class="d-none d-md-inline text-start"><span class="d-block" style="line-height:1.05">{display_name}</span>{f'<small class="text-secondary">{position}</small>' if position else ''}</span>
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end shadow-sm">
                        <li><a class="dropdown-item" href="/profile"><i data-feather="user" class="me-2"></i>Profile</a></li>
                        {billing_item}
                        <li><hr class="dropdown-divider"></li>
                        <li><a class="dropdown-item" href="/logout"><i data-feather="log-out" class="me-2"></i>Sign out</a></li>
                    </ul>
                </div>'''
    body = body.replace(top_login, account_menu, 1)

    side_login = '''<a class="list-group-item list-group-item-action bg-dark text-light border-secondary" href="/login">
                    <i data-feather="log-in" class="me-1"></i>Login
                </a>'''
    side_account = '''<a class="list-group-item list-group-item-action bg-dark text-light border-secondary" href="/profile">
                    <i data-feather="user" class="me-2"></i>Profile
                </a>'''
    if _is_owner(member):
        side_account += '''
                <a class="list-group-item list-group-item-action bg-dark text-light border-secondary" href="/billing">
                    <i data-feather="credit-card" class="me-2"></i>Billing
                </a>'''
    side_account += '''
                <a class="list-group-item list-group-item-action bg-dark text-light border-secondary" href="/logout">
                    <i data-feather="log-out" class="me-2"></i>Sign out
                </a>'''
    body = body.replace(side_login, side_account, 1)

    response.set_data(body)
    return response
