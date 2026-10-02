from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "governed_routes.py"
STORES = ROOT / "templates" / "stores.html"


def _text(path):
    return path.read_text(encoding="utf-8")


def test_stores_uses_marketplace_consent_not_temporary_setup():
    text = _text(STORES)
    assert "/amazon-oauth/authorize" in text
    assert "/ebay-oauth/authorize" in text
    assert "/ebay-oauth/authorize?store_id=" not in text
    assert "img/marketplaces/amazon.png" in text
    assert "img/marketplaces/ebay.png" in text
    assert "Quick Setup" not in text
    assert "submitAmazonSetupUnified" not in text
    assert "/governed/stores/amazon/setup-preview" not in text


def test_amazon_governed_oauth_is_customer_bound():
    text = _text(ROUTES)
    assert '@governed_bp.get("/amazon-oauth/authorize")' in text
    assert '@governed_bp.get("/amazon/callback")' in text
    assert '@governed_bp.get("/amazon-oauth/callback")' in text
    assert 'session["governed_amazon_oauth_account_id"] = account_id' in text
    assert 'Store.account_id == current_account_id' in text
    assert 'account_id=current_account_id' in text
    assert '"https://api.amazon.com/auth/o2/token"' in text


def test_ebay_governed_oauth_supports_fresh_customer_without_cross_account_store_selection():
    text = _text(ROUTES)
    assert "Store.account_id == account_id" in text
    assert 'session["governed_ebay_oauth_account_id"] = account_id' in text
    assert 'session["governed_ebay_oauth_store_id"] = store.id if store else None' in text
    assert 'account_id=current_account_id' in text
    assert '"account_mismatch"' in text


def test_ebay_governed_oauth_uses_signed_callback_handoff():
    text = _text(ROUTES)
    assert 'session["governed_ebay_oauth_state"] = state' in text
    assert '"bt38_ebay_oauth_handoff"' in text
    assert 'salt="bt38-ebay-oauth-state"' in text
    assert ').loads(str(state), max_age=900)' in text
    assert ').loads(str(handoff), max_age=900)' in text
    assert 'if not state and authorized_account_id and pending_states:' not in text
    assert 'oauth_account_id = state_account_id or int(authorized_account_id or 0)' in text
    assert 'current_account_id is None or oauth_account_id != int(current_account_id)' in text
    assert 'ebay_error = request.args.get("error")' in text
    assert '"error_description": ebay_error_description' in text


def test_legacy_ebay_customer_templates_use_only_governed_authorize():
    for relative in ("templates/ebay_oauth.html", "templates/ebay_setup.html"):
        text = _text(ROOT / relative)
        assert "/ebay-oauth/authorize" in text
        assert "/ebay-oauth/start" not in text
        assert 'name="access_token"' not in text
        assert 'name="refresh_token"' not in text
        assert 'name="cert_id"' not in text
