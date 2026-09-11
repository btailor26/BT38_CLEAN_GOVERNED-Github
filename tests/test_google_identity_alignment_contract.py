from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


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
    assert 'session.get("_remember") == "set"' in public_service
    assert 'app.config.get("REMEMBER_COOKIE_NAME", "remember_token")' in public_service


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
