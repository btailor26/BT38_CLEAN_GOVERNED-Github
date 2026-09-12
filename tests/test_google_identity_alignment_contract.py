from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _compact(value: str) -> str:
    """Normalize formatting only; contracts still prove the same executable facts."""
    return re.sub(r"\s+", "", value)


def test_google_sign_in_stays_on_existing_login_authority():
    public_service = _read("services/public_early_access.py")
    landing = _read("templates/public_landing.html")

    assert 'path != "/login"' in public_service
    assert 'request.form.get("credential")' in public_service
    assert 'login_user(user, remember=False, fresh=True)' in public_service
    assert 'User.query.filter(User.email.ilike(email)).first()' in public_service
    assert 'url_for("governed.login"' in public_service

    assert 'data-login_uri="{{ google_login_uri }}"' in landing
    assert 'action="{{ url_for(\'governed.login\') }}"' in landing
    assert 'https://accounts.google.com/gsi/client' in landing
    assert 'data-use_fedcm_for_button="true"' in landing


def test_google_sign_in_does_not_create_parallel_users_or_sessions():
    public_service = _read("services/public_early_access.py")

    google_login_block = public_service.split("def bt38_google_identity_login", 1)[1].split(
        '@app.get("/forgot-password")', 1
    )[0]

    assert "User(" not in google_login_block
    assert "db.session.add(user" not in google_login_block
    assert "remember=True" not in google_login_block


def test_google_post_csrf_and_token_validation_are_required():
    public_service = _read("services/public_early_access.py")
    verifier = _read("services/google_identity.py")

    assert 'request.cookies.get("g_csrf_token")' in public_service
    assert 'request.form.get("g_csrf_token")' in public_service
    assert "hmac.compare_digest" in public_service
    assert "verify_google_id_token(credential, client_id)" in public_service

    assert 'header.get("alg") != "RS256"' in verifier
    assert 'claims.get("iss")' in verifier
    assert '_audience_matches(claims.get("aud"), client_id)' in verifier
    assert 'claims.get("exp")' in verifier
    assert "_verify_signature" in verifier
    assert "GOOGLE_JWKS_URL" in verifier


def test_google_client_secret_is_not_required_for_identity_only_flow():
    files = [
        _read("services/public_early_access.py"),
        _read("services/google_identity.py"),
        _read("templates/public_landing.html"),
        _read("templates/forgot_password.html"),
    ]
    combined = "\n".join(files)

    assert "GOOGLE_CLIENT_ID" in combined
    assert "GOOGLE_CLIENT_SECRET" not in combined


def test_existing_password_form_is_browser_password_manager_friendly():
    landing = _read("templates/public_landing.html")
    reset = _read("templates/reset_password.html")

    assert 'autocomplete="username"' in landing
    assert 'autocomplete="current-password"' in landing
    assert 'autocomplete="username"' in reset
    assert 'autocomplete="new-password"' in reset


def test_bt38_browser_session_is_first_party_fresh_and_password_bound():
    public_service = _read("services/public_early_access.py")

    assert 'app.config["SESSION_COOKIE_SECURE"] = True' in public_service
    assert 'app.config["SESSION_COOKIE_HTTPONLY"] = True' in public_service
    assert 'app.config["SESSION_COOKIE_SAMESITE"] = "Lax"' in public_service
    assert 'app.config["SESSION_REFRESH_EACH_REQUEST"] = True' in public_service
    assert 'app.config["REMEMBER_COOKIE_SECURE"] = True' in public_service
    assert 'app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"' in public_service
    assert "session.permanent = True" in public_service
    assert "if not login_fresh():" in public_service
    assert '_AUTH_STAMP_SESSION_KEY = "bt38_auth_stamp"' in public_service
    assert "current_stamp = _auth_stamp(current_user)" in public_service
    assert "if not expected_stamp:" in public_service
    assert "session[_AUTH_STAMP_SESSION_KEY] = current_stamp" in public_service
    assert "if not hmac.compare_digest(expected_stamp, current_stamp):" in public_service
    assert 'session.get("_remember") == "set"' in public_service
    assert 'app.config.get("REMEMBER_COOKIE_NAME", "remember_token")' in public_service


def test_legacy_remember_cookie_is_retired_before_main_auth_guard():
    main = _read("main.py")
    cleanup = _read("services/auth_session_legacy_cleanup.py")

    compile(cleanup, "services/auth_session_legacy_cleanup.py", "exec")

    assert main.index("import services.auth_session_legacy_cleanup") < main.index(
        "import services.public_early_access"
    )
    assert 'if path == "/logout":' in cleanup
    assert "if current_user.is_authenticated and not login_fresh():" in cleanup
    assert 'app.config.get("REMEMBER_COOKIE_NAME", "remember_token")' in cleanup
    assert 'app.config.get("SESSION_COOKIE_NAME", "session")' in cleanup
    assert "return _expire_bt38_auth_cookies(response)" in cleanup

    end_block = cleanup.split("def _end_auth_session_once", 1)[1].split(
        "@app.before_request", 1
    )[0]
    assert "    session.clear()\n    logout_user()\n" in end_block
    assert "    logout_user()\n    session.clear()\n" not in end_block


def test_customer_profile_extends_existing_auth_and_only_gates_new_users():
    cleanup = _read("services/auth_session_legacy_cleanup.py")
    profile_service = _read("services/account_profile_alignment.py")
    first_login = _read("templates/profile_first_login.html")
    compact = _compact(profile_service)

    compile(profile_service, "services/account_profile_alignment.py", "exec")
    assert "import services.account_profile_alignment" in cleanup
    assert "frommodelsimportSystemLog,User" in compact
    assert "login_user(" not in profile_service
    assert "verify_google_id_token" not in profile_service
    assert "setup_required=bool(approved)" in compact
    assert "setup_completed_at=Noneifapprovedelsedatetime.utcnow()" in compact
    assert "ifnotp.setup_required:returnNone" in compact
    assert 'pathin_PROFILE_ALLOWED_PATHS' in compact
    assert 'name="username"' in first_login
    assert 'name="display_name"' in first_login
    assert 'name="position"' in first_login
    assert "Continue to dashboard" in first_login
    assert "No setup wizard" in first_login


def test_customer_account_owns_branding_five_seats_and_role_presets():
    profile_service = _read("services/account_profile_alignment.py")
    profile_page = _read("templates/profile.html")
    billing_page = _read("templates/billing.html")
    migration = _read("migrations/manual/20260911-customer-account-profile.sql")
    compact = _compact(profile_service)

    assert 'user_limit=db.Column(db.Integer,nullable=False,default=5)' in compact
    assert '_member_count(a.id)>=int(a.user_limitor5)' in compact
    assert '"warehouse_manager"' in profile_service
    assert '"purchasing_manager"' in profile_service
    assert '"content_manager"' in profile_service
    assert '"assistant"' in profile_service
    assert 'manage_users=bool(manage_users)' in compact
    assert "Position is not permission." in profile_page
    assert "including the owner" in profile_page

    assert "logo_data=db.Column(db.LargeBinary" in compact
    assert "image/png" in profile_service
    assert "image/jpeg" in profile_service
    assert "image/webp" in profile_service
    assert "Powered by BT38" in profile_service
    assert "Powered by BT38" in profile_page
    assert "customer_accounts" in migration
    assert "customer_account_members" in migration
    assert "user_profiles" in migration

    # Billing remains the account/package surface. It uses the existing account
    # and package authority rather than defining another user/subscription model.
    assert '@app.get("/billing")' in profile_service
    assert "bt38_package_for_account(account.id)" in billing_page
    assert "BT38 controls package entitlement, billing history and billing documents." in billing_page
    assert "class CustomerAccount" not in billing_page
    assert "class User" not in billing_page
    assert "stripe" not in profile_service.lower()
    assert "paypal" not in profile_service.lower()


def test_customer_team_role_safety_does_not_grant_content_stock_write_and_aligns_existing_users():
    cleanup = _read("services/auth_session_legacy_cleanup.py")
    safety = _read("services/account_profile_role_safety.py")

    compile(safety, "services/account_profile_role_safety.py", "exec")
    assert "import services.account_profile_role_safety" in cleanup
    assert 'ROLE_PRESETS["content_manager"]' in safety
    assert '_content["role"] = "viewer"' in safety
    assert 'key.startswith("edit_")' in safety
    assert '_content["permissions"][key] = False' in safety
    assert 'request.path.rstrip("/") != "/profile/team/add"' in safety
    assert "profile = db.session.get(UserProfile, user.id)" in safety
    assert "setup_required=True" in safety
    assert "profile.setup_required = True" in safety
    assert "membership.account_id != account.id" in safety


def test_customer_shell_only_rebrands_after_customer_logo_exists():
    profile_service = _read("services/account_profile_alignment.py")
    shell_block = profile_service.split("def bt38_customer_owned_shell_alignment", 1)[1]
    compact = _compact(shell_block)

    assert "ifaanda.logo_data:" in compact
    assert "BT38 Inventory" in shell_block
    assert "Powered by BT38" in shell_block
    assert 'href="/profile"' in shell_block
    assert 'href="/billing"' in shell_block
    assert 'href="/logout"' in shell_block


def test_first_login_hands_once_to_cofi_dashboard_welcome():
    cleanup = _read("services/auth_session_legacy_cleanup.py")
    profile_service = _read("services/account_profile_alignment.py")
    welcome_service = _read("services/cofi_first_welcome_alignment.py")
    compact = _compact(profile_service)

    compile(welcome_service, "services/cofi_first_welcome_alignment.py", "exec")
    assert "import services.cofi_first_welcome_alignment" in cleanup
    assert 'session["bt38_cofi_first_welcome"]=name' in compact or 'session["bt38_cofi_first_welcome"]=display_name' in compact
    assert 'session.pop("bt38_cofi_first_welcome", "")' in welcome_service
    assert 'data-bt38-cofi-first-welcome="true"' in welcome_service
    assert "I’m COFI." in welcome_service
    assert "Nothing else to set up right now." in welcome_service
    assert 'request.path.rstrip("/")' in welcome_service
    assert '"/dashboard"' in welcome_service


def test_forgot_password_reuses_existing_google_login_callback():
    public_service = _read("services/public_early_access.py")
    landing = _read("templates/public_landing.html")
    forgot = _read("templates/forgot_password.html")
    reset = _read("templates/reset_password.html")

    assert '@app.get("/forgot-password")' in public_service
    assert '@app.route("/reset-password", methods=["GET", "POST"])' in public_service
    assert '@app.post("/forgot-password/google")' not in public_service
    assert 'google_reset_uri=_google_login_uri()' in public_service
    assert "reset_requested = _password_reset_intent_active()" in public_service
    assert "_grant_password_reset(user)" in public_service
    assert "_PASSWORD_RESET_MINUTES = 10" in public_service
    assert "session[_RESET_STAMP_SESSION_KEY] = _auth_stamp(user)" in public_service
    assert "user.set_password(new_password)" in public_service
    assert "session.clear()" in public_service
    assert "login_user(user" not in public_service.split("def bt38_public_password_reset", 1)[1].split("def _application_payload", 1)[0]

    assert "Forgot password?" in landing
    assert "bt38_public_forgot_password" in landing
    assert 'data-login_uri="{{ google_reset_uri }}"' in forgot
    assert 'data-use_fedcm_for_button="true"' in forgot
    assert 'name="reset_csrf"' in reset
    assert 'minlength="8"' in reset
