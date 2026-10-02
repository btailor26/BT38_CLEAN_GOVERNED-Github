from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "governed_routes.py").read_text(encoding="utf-8")
CONCURRENCY_TEST = (ROOT / "test_concurrent_sales.py").read_text(encoding="utf-8")
PYTEST_GATE = (ROOT / "conftest.py").read_text(encoding="utf-8")


def test_ebay_oauth_never_selects_the_newest_store():
    oauth = ROUTES.split("def _resolve_governed_ebay_oauth_store", 1)[1]
    oauth = oauth.split("@governed_bp.post(\"/ebay-oauth/token\")", 1)[0]

    assert "order_by(Store.id.desc()).first()" not in oauth
    assert 'session["governed_ebay_oauth_store_id"] = store.id' in oauth
    assert "selected_store_id = session.get(\"governed_ebay_oauth_store_id\")" in oauth
    assert '"error": "ebay_store_selection_required"' in oauth


def test_refresh_requires_an_explicit_or_unambiguous_live_store():
    refresh = ROUTES.split("def governed_ebay_oauth_refresh_token():", 1)[1]

    assert 'payload.get("store_id") or request.args.get("store_id")' in refresh
    assert "_resolve_governed_ebay_oauth_store(selected_store_id)" in refresh
    assert "order_by(Store.id.desc()).first()" not in refresh


def test_database_writing_concurrency_tests_are_blocked_in_prod():
    assert 'app_env in {"PROD", "PRODUCTION"}' in CONCURRENCY_TEST
    assert '"ep-royal-fire-ai8c32qw" in database_uri' in CONCURRENCY_TEST
    assert 'os.getenv("BT38_ALLOW_DATABASE_TESTS")' in CONCURRENCY_TEST


def test_all_pytest_execution_is_blocked_before_collection_in_prod():
    assert "def pytest_sessionstart(session):" in PYTEST_GATE
    assert 'app_env in {"PROD", "PRODUCTION"}' in PYTEST_GATE
    assert '"ep-royal-fire-ai8c32qw"' in PYTEST_GATE
    assert 'os.getenv("BT38_ALLOW_DATABASE_TESTS")' in PYTEST_GATE


def test_ebay_no_state_callback_keeps_signed_customer_handoff_outside_temp_session():
    oauth = ROUTES.split("@governed_bp.get(\"/ebay-oauth/authorize\")", 1)[1]
    oauth = oauth.split("@governed_bp.post(\"/ebay-oauth/token\")", 1)[0]

    assert 'response.set_cookie(' in oauth
    assert '"bt38_ebay_oauth_handoff"' in oauth
    assert 'max_age=900' in oauth
    assert 'secure=True' in oauth
    assert 'httponly=True' in oauth
    assert 'samesite="Lax"' in oauth
    assert 'path="/ebay-oauth/callback"' in oauth
    assert 'request.cookies.get("bt38_ebay_oauth_handoff")' in oauth
    assert 'salt="bt38-ebay-oauth-state"' in oauth
    assert ').loads(str(handoff), max_age=900)' in oauth
    assert 'state_account_id = int(handoff_payload.get("account_id") or 0)' in oauth
    assert 'oauth_account_id = state_account_id or int(authorized_account_id or 0)' in oauth
    assert 'oauth_account_id != int(current_account_id)' in oauth


def test_ebay_state_mismatch_flows_through_existing_failure_recorder():
    callback = ROUTES.split("def governed_ebay_oauth_callback():", 1)[1]
    callback = callback.split("@governed_bp.post(\"/ebay-oauth/token\")", 1)[0]

    mismatch = callback.split('"error": "state_mismatch"', 1)[1]
    assert "}), 400" in mismatch[:80]


def test_ebay_oauth_keeps_only_one_state_in_client_session():
    authorize = ROUTES.split("def governed_ebay_oauth_authorize():", 1)[1]
    authorize = authorize.split("@governed_bp.get(\"/ebay-oauth/callback\")", 1)[0]
    callback = ROUTES.split("def governed_ebay_oauth_callback():", 1)[1]
    callback = callback.split("@governed_bp.post(\"/ebay-oauth/token\")", 1)[0]

    assert 'session.pop("governed_ebay_oauth_pending_states", None)' in authorize
    assert 'session["governed_ebay_oauth_state"] = state' in authorize
    assert 'pending_states.append(state)' not in authorize
    assert 'pending_states[-5:]' not in authorize
    assert 'session.get("governed_ebay_oauth_pending_states")' not in callback
    assert 'pending_states = {str(expected_state)} if expected_state else set()' in callback


def test_legacy_ebay_auth_callback_is_retired_before_oauth_processing():
    callback = ROUTES.split("def governed_ebay_oauth_callback():", 1)[1]
    callback = callback.split("@governed_bp.post(\"/ebay-oauth/token\")", 1)[0]

    assert '("ebaytkn", "tknexp", "username")' in callback
    assert '"error": "legacy_ebay_auth_retired"' in callback
    retired = callback.split('"error": "legacy_ebay_auth_retired"', 1)[1]
    assert "}), 410" in retired[:80]
    assert "GetSessionID" not in callback
    assert "FetchToken" not in callback
    assert "SessID" not in callback


def test_ebay_customer_connection_uses_oauth_authorization_code_only():
    authorize = ROUTES.split("def governed_ebay_oauth_authorize():", 1)[1]
    authorize = authorize.split("@governed_bp.get(\"/ebay-oauth/callback\")", 1)[0]

    assert '"https://auth.ebay.com/oauth2/authorize?"' in authorize
    assert '"response_type": "code"' in authorize
    assert '"redirect_uri": runame' in authorize
    assert '"state": state' in authorize
    assert "signin.ebay.com" not in authorize
    assert "GetSessionID" not in authorize
    assert "FetchToken" not in authorize
