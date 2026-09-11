"""Retire legacy Flask-Login remember cookies without creating auth loops.

BT38 now uses one first-party Flask session for both Google and manual login.
Older browsers may still carry the previous Flask-Login remember_token cookie.
This module runs before the current auth alignment guard so that a remembered,
non-fresh identity is ended once, both legacy cookies are expired, and the
browser reaches /login on the next request instead of being restored forever.
"""
from __future__ import annotations

from flask import redirect, request, session, url_for
from flask_login import current_user, login_fresh, logout_user

from app import app


def _delete_cookie(response, *, name: str, path: str, domain):
    response.delete_cookie(
        name,
        path=path or "/",
        domain=domain,
        secure=True,
        httponly=True,
        samesite="Lax",
    )
    return response


def _expire_bt38_auth_cookies(response):
    """Expire both the retired remember cookie and the current BT38 session."""
    _delete_cookie(
        response,
        name=app.config.get("REMEMBER_COOKIE_NAME", "remember_token"),
        path=app.config.get("REMEMBER_COOKIE_PATH") or "/",
        domain=app.config.get("REMEMBER_COOKIE_DOMAIN"),
    )
    _delete_cookie(
        response,
        name=app.config.get("SESSION_COOKIE_NAME", "session"),
        path=app.config.get("SESSION_COOKIE_PATH") or "/",
        domain=app.config.get("SESSION_COOKIE_DOMAIN"),
    )
    return response


def _end_auth_session_once():
    """End auth while preserving Flask-Login's remember-cookie clear signal."""
    # Clear BT38 state first. logout_user() must run afterwards because it sets
    # Flask-Login's internal _remember='clear' marker when a legacy cookie is
    # present. Clearing the session after logout_user() would erase that marker
    # and let the browser restore the same remembered identity again.
    session.clear()
    logout_user()

    response = redirect(url_for("governed.login"))
    return _expire_bt38_auth_cookies(response)


@app.before_request
def bt38_legacy_remember_cookie_cleanup():
    """Convert old remembered browsers to one clean BT38 login request."""
    path = request.path.rstrip("/") or "/"

    # Own logout before the older governed route executes. That route predates
    # the current single-session policy and must not be allowed to leave a
    # remember cookie behind.
    if path == "/logout":
        if current_user.is_authenticated:
            return _end_auth_session_once()

        response = redirect(url_for("governed.login"))
        return _expire_bt38_auth_cookies(response)

    # A non-fresh Flask-Login identity is a legacy remember-cookie restoration,
    # not a valid BT38 browser session. Expire it once and redirect to /login.
    # The following request arrives without that cookie, so there is no loop.
    if current_user.is_authenticated and not login_fresh():
        return _end_auth_session_once()

    return None


# The customer account/profile layer extends this same single-session authority.
# Load it after legacy-cookie cleanup is registered and before the public Google
# handler, so a valid fresh login can enter one-time profile setup without a
# second auth path or session implementation.
import services.account_profile_alignment  # noqa: E402,F401
# First-login setup hands directly to the real dashboard. Consume its one-time
# COFI welcome marker there without adding a setup wizard or parallel dashboard.
import services.cofi_first_welcome_alignment  # noqa: E402,F401
