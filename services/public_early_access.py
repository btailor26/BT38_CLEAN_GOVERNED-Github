"""Public early-access application workflow for BT38 Inventory.

Scope:
- public landing and application intake only
- public privacy, terms and support pages
- store application evidence in existing SystemLog
- no marketplace calls
- no stock/sync/push/import execution
- no automatic user creation
- approved applicants are handed to existing governed user management
- Google Identity verifies approved users into the existing BT38 session only
- password reset reuses Google Identity as proof for the existing BT38 User
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import json
import os
import secrets
from urllib.parse import quote

from flask import redirect, render_template, request, url_for, flash, session
from flask_login import (
    current_user,
    login_fresh,
    login_required,
    login_user,
    logout_user,
)

from app import app
from extensions import db
from models import SystemLog, User
from services.google_identity import GoogleIdentityError, verify_google_id_token


# Google proves identity; BT38 keeps the existing first-party Flask session as
# the sole application session authority.
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_REFRESH_EACH_REQUEST"] = True
app.config["REMEMBER_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"

_PASSWORD_RESET_MINUTES = 10
_AUTH_STAMP_SESSION_KEY = "bt38_auth_stamp"
_RESET_INTENT_EXPIRES_SESSION_KEY = "bt38_password_reset_intent_expires_at"
_RESET_USER_SESSION_KEY = "bt38_password_reset_user_id"
_RESET_EXPIRES_SESSION_KEY = "bt38_password_reset_expires_at"
_RESET_STAMP_SESSION_KEY = "bt38_password_reset_auth_stamp"
_RESET_CSRF_SESSION_KEY = "bt38_password_reset_csrf"


def _clean(value: str, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _safe_login_next() -> str:
    requested_next = request.args.get("next") or request.form.get("next") or ""
    if requested_next.startswith("/") and not requested_next.startswith("//") and "\\" not in requested_next:
        return requested_next
    return url_for("governed.governed_warehouse_page")


def _google_client_id() -> str:
    return str(os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def _google_login_uri() -> str:
    return (
        url_for("governed.login", _external=True, _scheme="https")
        if _google_client_id()
        else ""
    )


def _auth_stamp(user: User) -> str:
    """Bind a browser session to the user's current BT38 password hash."""
    secret = str(app.secret_key or "").encode("utf-8")
    material = f"{int(user.id)}:{str(user.password_hash or '')}".encode("utf-8")
    return hmac.new(secret, material, hashlib.sha256).hexdigest()


def _clear_password_reset_grant() -> None:
    for key in (
        _RESET_USER_SESSION_KEY,
        _RESET_EXPIRES_SESSION_KEY,
        _RESET_STAMP_SESSION_KEY,
        _RESET_CSRF_SESSION_KEY,
    ):
        session.pop(key, None)


def _clear_password_reset_state() -> None:
    session.pop(_RESET_INTENT_EXPIRES_SESSION_KEY, None)
    _clear_password_reset_grant()


def _password_reset_intent_active() -> bool:
    raw = session.get(_RESET_INTENT_EXPIRES_SESSION_KEY)
    if raw in (None, ""):
        return False
    try:
        expires_at = float(raw)
    except (TypeError, ValueError):
        session.pop(_RESET_INTENT_EXPIRES_SESSION_KEY, None)
        return False
    if expires_at <= datetime.utcnow().timestamp():
        session.pop(_RESET_INTENT_EXPIRES_SESSION_KEY, None)
        return False
    return True


def _grant_password_reset(user: User) -> None:
    _clear_password_reset_grant()
    session.pop(_RESET_INTENT_EXPIRES_SESSION_KEY, None)
    session[_RESET_USER_SESSION_KEY] = int(user.id)
    session[_RESET_EXPIRES_SESSION_KEY] = (
        datetime.utcnow() + timedelta(minutes=_PASSWORD_RESET_MINUTES)
    ).timestamp()
    session[_RESET_STAMP_SESSION_KEY] = _auth_stamp(user)
    session[_RESET_CSRF_SESSION_KEY] = secrets.token_urlsafe(32)


def _password_reset_user():
    try:
        user_id = int(session.get(_RESET_USER_SESSION_KEY) or 0)
        expires_at = float(session.get(_RESET_EXPIRES_SESSION_KEY) or 0)
    except (TypeError, ValueError):
        _clear_password_reset_grant()
        return None

    if not user_id or expires_at <= datetime.utcnow().timestamp():
        _clear_password_reset_grant()
        return None

    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        _clear_password_reset_grant()
        return None

    expected_stamp = str(session.get(_RESET_STAMP_SESSION_KEY) or "")
    current_stamp = _auth_stamp(user)
    if not expected_stamp or not hmac.compare_digest(expected_stamp, current_stamp):
        _clear_password_reset_grant()
        return None

    return user


def _forgot_password_page(error: str = "", status: int = 200):
    return render_template(
        "forgot_password.html",
        error=error,
        google_client_id=_google_client_id(),
        google_reset_uri=_google_login_uri(),
    ), status


@app.before_request
def bt38_browser_session_alignment():
    """Keep authenticated browsing on one fresh, password-bound BT38 session."""
    if not current_user.is_authenticated:
        return None

    if request.path == "/logout":
        return None

    # A Flask-Login remember cookie is not a second BT38 session authority.
    if not login_fresh():
        logout_user()
        session.clear()
        return redirect(url_for("governed.login"))

    expected_stamp = str(session.get(_AUTH_STAMP_SESSION_KEY) or "")
    current_stamp = _auth_stamp(current_user)
    if not expected_stamp or not hmac.compare_digest(expected_stamp, current_stamp):
        logout_user()
        session.clear()
        return redirect(url_for("governed.login"))

    return None


@app.after_request
def bt38_browser_session_response_alignment(response):
    """Stamp fresh logins and suppress the legacy remember-cookie side effect."""
    if current_user.is_authenticated and login_fresh():
        # app.py already sets PERMANENT_SESSION_LIFETIME to 30 minutes. Mark the
        # live browser session permanent so that configured sliding lifetime is
        # actually used while the user remains active.
        session.permanent = True
        session[_AUTH_STAMP_SESSION_KEY] = _auth_stamp(current_user)

        # Existing manual /login still calls remember=True. Keep that route
        # intact, but remove its remember-cookie request so both login methods
        # finish on the same first-party BT38 session.
        if session.get("_remember") == "set":
            session.pop("_remember", None)

        response.delete_cookie(
            app.config.get("REMEMBER_COOKIE_NAME", "remember_token"),
            secure=True,
            httponly=True,
            samesite="Lax",
        )

        # A successful manual password login cancels any abandoned reset intent.
        if (
            request.path.rstrip("/") == "/login"
            and request.method == "POST"
            and not str(request.form.get("credential") or "").strip()
        ):
            _clear_password_reset_state()

    return response


@app.context_processor
def bt38_google_identity_context():
    """Expose only the public Google client ID and existing BT38 login URI."""
    return {
        "google_client_id": _google_client_id(),
        "google_login_uri": _google_login_uri(),
    }


def _verify_google_post():
    """Verify Google GIS double-submit CSRF and the signed Google ID token."""
    client_id = _google_client_id()
    if not client_id:
        return None, "Google sign-in is not configured for BT38 Inventory."

    csrf_cookie = str(request.cookies.get("g_csrf_token") or "")
    csrf_form = str(request.form.get("g_csrf_token") or "")
    if not csrf_cookie or not csrf_form or not hmac.compare_digest(csrf_cookie, csrf_form):
        return None, "Google verification could not be completed. Please try again."

    credential = str(request.form.get("credential") or "").strip()
    if not credential:
        return None, "Google verification could not be completed. Please try again."

    try:
        return verify_google_id_token(credential, client_id), ""
    except GoogleIdentityError:
        return None, "Google verification could not be completed. Please try again."


@app.before_request
def bt38_google_identity_login():
    """Handle Google identity on the existing /login authority only."""
    path = request.path.rstrip("/") or "/"
    credential = str(request.form.get("credential") or "").strip()
    if request.method != "POST" or path != "/login" or not credential:
        return None

    next_url = _safe_login_next()
    reset_requested = _password_reset_intent_active()
    claims, google_error = _verify_google_post()
    if not claims:
        if reset_requested:
            return _forgot_password_page(google_error, 401)
        return render_template(
            "login.html",
            error=google_error,
            next_url=next_url,
        ), 401

    email = str(claims.get("email") or "").strip().lower()
    user = User.query.filter(User.email.ilike(email)).first()

    if reset_requested:
        if not user or not user.is_active:
            return _forgot_password_page(
                "This Google account cannot be used to reset a BT38 password. Use the Google account that matches your approved BT38 email, or contact your BT38 administrator.",
                403,
            )

        _grant_password_reset(user)
        db.session.add(SystemLog(
            log_type="authentication",
            message="Google password-reset identity verified",
            details=json.dumps({
                "provider": "google",
                "user_id": user.id,
                "verified_at": datetime.utcnow().isoformat() + "Z",
            }),
        ))
        db.session.commit()
        return redirect(url_for("bt38_public_password_reset"))

    if not user or not user.is_active:
        return render_template(
            "login.html",
            error="This Google account is not linked to an active BT38 Inventory account. Apply for access or use the email on your approved account.",
            next_url=next_url,
        ), 403

    _clear_password_reset_state()
    user.last_login = datetime.utcnow()
    db.session.add(SystemLog(
        log_type="authentication",
        message="Google sign-in succeeded",
        details=json.dumps({
            "provider": "google",
            "user_id": user.id,
            "select_by": _clean(request.form.get("select_by"), 40),
            "signed_in_at": datetime.utcnow().isoformat() + "Z",
        }),
    ))
    db.session.commit()

    # Keep one session authority: the existing Flask-Login session.
    login_user(user, remember=False, fresh=True)
    return redirect(next_url)


@app.get("/forgot-password")
def bt38_public_forgot_password():
    """Begin a zero-email-cost reset using the existing Google /login callback."""
    _clear_password_reset_state()
    session[_RESET_INTENT_EXPIRES_SESSION_KEY] = (
        datetime.utcnow() + timedelta(minutes=_PASSWORD_RESET_MINUTES)
    ).timestamp()
    return _forgot_password_page()


@app.route("/reset-password", methods=["GET", "POST"])
def bt38_public_password_reset():
    """Reset the existing BT38 password after a short-lived Google proof."""
    user = _password_reset_user()
    if not user:
        return redirect(url_for("bt38_public_forgot_password"))

    reset_csrf = str(session.get(_RESET_CSRF_SESSION_KEY) or "")
    if request.method == "GET":
        return render_template(
            "reset_password.html",
            error="",
            reset_csrf=reset_csrf,
            user_email=user.email,
        )

    submitted_csrf = str(request.form.get("reset_csrf") or "")
    if not reset_csrf or not submitted_csrf or not hmac.compare_digest(reset_csrf, submitted_csrf):
        _clear_password_reset_state()
        return _forgot_password_page(
            "Your password reset could not be verified. Please verify with Google again.",
            400,
        )

    new_password = str(request.form.get("new_password") or "")
    confirm_password = str(request.form.get("confirm_password") or "")
    if len(new_password) < 8:
        return render_template(
            "reset_password.html",
            error="Use at least 8 characters for your new password.",
            reset_csrf=reset_csrf,
            user_email=user.email,
        ), 400
    if new_password != confirm_password:
        return render_template(
            "reset_password.html",
            error="The two passwords do not match.",
            reset_csrf=reset_csrf,
            user_email=user.email,
        ), 400

    user.set_password(new_password)
    user.updated_at = datetime.utcnow()
    db.session.add(SystemLog(
        log_type="authentication",
        message="BT38 password reset completed",
        details=json.dumps({
            "user_id": user.id,
            "reset_at": datetime.utcnow().isoformat() + "Z",
        }),
    ))
    db.session.commit()

    # Do not auto-login after a password change. End this browser session and
    # remove any legacy remember cookie. Other stamped sessions fail the new
    # password-hash binding on their next request.
    logout_user()
    session.clear()
    flash("Password updated. Sign in again with your new BT38 password.", "success")
    response = redirect(url_for("governed.login"))
    response.delete_cookie(
        app.config.get("REMEMBER_COOKIE_NAME", "remember_token"),
        secure=True,
        httponly=True,
        samesite="Lax",
    )
    return response


def _application_payload() -> dict:
    marketplaces = [
        name
        for name in ("Amazon", "eBay", "Other")
        if request.form.get(f"marketplace_{name.lower()}") == "on"
    ]
    return {
        "status": "pending",
        "full_name": _clean(request.form.get("full_name"), 120),
        "business_name": _clean(request.form.get("business_name"), 160),
        "email": _clean(request.form.get("email"), 160).lower(),
        "marketplaces": marketplaces,
        "monthly_orders": _clean(request.form.get("monthly_orders"), 80),
        "goals": _clean(request.form.get("goals"), 2000),
        "submitted_at": datetime.utcnow().isoformat() + "Z",
        "source": "bt38_public_early_access",
    }


def _load_details(row: SystemLog) -> dict:
    try:
        data = json.loads(row.details or "{}")
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


@app.before_request
def bt38_public_root_landing():
    """Show the public website directly at / without changing route authority."""
    if request.method != "GET" or (request.path.rstrip("/") or "/") != "/":
        return None
    if current_user.is_authenticated:
        return None
    session.pop(_RESET_INTENT_EXPIRES_SESSION_KEY, None)
    return render_template(
        "public_landing.html",
        error="",
        next_url=url_for("governed.governed_warehouse_page"),
    )


@app.get("/privacy")
def bt38_public_privacy():
    return render_template("privacy.html")


@app.get("/terms")
def bt38_public_terms():
    return render_template("terms.html")


@app.get("/support")
def bt38_public_support():
    return render_template("support.html")


@app.route("/apply", methods=["GET", "POST"])
def bt38_early_access_apply():
    if current_user.is_authenticated:
        return redirect(url_for("governed.governed_dashboard_page"))

    if request.method == "GET":
        return render_template("early_access_apply.html")

    payload = _application_payload()
    required = (
        payload["full_name"],
        payload["business_name"],
        payload["email"],
        payload["goals"],
    )
    if not all(required) or "@" not in payload["email"]:
        return render_template(
            "early_access_apply.html",
            error="Please complete your name, business name, valid email and what you want to manage with BT38 Inventory.",
            form=request.form,
        ), 400

    existing_user = User.query.filter(User.email.ilike(payload["email"])).first()
    if existing_user:
        flash("An approved BT38 Inventory account already exists for this email. Please sign in.", "info")
        return redirect(url_for("governed.login"))

    recent = (
        SystemLog.query
        .filter(SystemLog.log_type == "early_access_application")
        .order_by(SystemLog.created_at.desc())
        .limit(250)
        .all()
    )
    for row in recent:
        details = _load_details(row)
        if str(details.get("email") or "").lower() == payload["email"] and details.get("status") in {"pending", "approved"}:
            return render_template(
                "early_access_received.html",
                application_id=row.id,
                existing=True,
            )

    row = SystemLog(
        log_type="early_access_application",
        message=f"Early access application: {payload['business_name']}",
        details=json.dumps(payload, ensure_ascii=False),
    )
    db.session.add(row)
    db.session.commit()

    return render_template(
        "early_access_received.html",
        application_id=row.id,
        existing=False,
    )


@app.get("/admin/early-access-applications")
@login_required
def bt38_early_access_applications_admin():
    if getattr(current_user, "role", "") != "admin":
        flash("You do not have permission to review early-access applications.", "danger")
        return redirect(url_for("governed.governed_dashboard_page"))

    rows = (
        SystemLog.query
        .filter(SystemLog.log_type == "early_access_application")
        .order_by(SystemLog.created_at.desc(), SystemLog.id.desc())
        .limit(500)
        .all()
    )
    applications = []
    for row in rows:
        details = _load_details(row)
        applications.append({
            "id": row.id,
            "created_at": row.created_at,
            **details,
        })

    return render_template(
        "admin/early_access_applications.html",
        applications=applications,
    )


@app.post("/admin/early-access-applications/<int:application_id>/<decision>")
@login_required
def bt38_early_access_application_decision(application_id: int, decision: str):
    if getattr(current_user, "role", "") != "admin":
        flash("You do not have permission to review early-access applications.", "danger")
        return redirect(url_for("governed.governed_dashboard_page"))

    decision = str(decision or "").strip().lower()
    if decision not in {"approved", "rejected", "pending"}:
        flash("Invalid application decision.", "danger")
        return redirect(url_for("bt38_early_access_applications_admin"))

    row = SystemLog.query.filter_by(
        id=application_id,
        log_type="early_access_application",
    ).first_or_404()

    details = _load_details(row)
    details["status"] = decision
    details["reviewed_at"] = datetime.utcnow().isoformat() + "Z"
    details["reviewed_by_user_id"] = getattr(current_user, "id", None)
    row.details = json.dumps(details, ensure_ascii=False)

    audit = SystemLog(
        log_type="early_access_application_review",
        message=f"Early access application {application_id}: {decision}",
        details=json.dumps({
            "application_id": application_id,
            "decision": decision,
            "email": details.get("email"),
            "reviewed_by_user_id": getattr(current_user, "id", None),
            "reviewed_at": details["reviewed_at"],
        }),
    )
    db.session.add(audit)
    db.session.commit()

    if decision == "approved":
        email = quote(str(details.get("email") or ""))
        username = quote(str(details.get("full_name") or ""))
        flash("Application approved. Create the BT38 Inventory account through the existing governed user workflow.", "success")
        return redirect(f"/users/create?email={email}&username={username}")

    flash(f"Application marked {decision}.", "success")
    return redirect(url_for("bt38_early_access_applications_admin"))
