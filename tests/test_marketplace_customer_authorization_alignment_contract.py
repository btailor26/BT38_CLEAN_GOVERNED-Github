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


def test_ebay_governed_oauth_keeps_bounded_pending_states_for_callback_handoff():
    text = _text(ROUTES)
    assert 'session["governed_ebay_oauth_pending_states"] = pending_states[-5:]' in text
    assert 'if not state or str(state) not in pending_states:' in text
    assert 'session.pop("governed_ebay_oauth_pending_states", None)' in text
    assert 'ebay_error = request.args.get("error")' in text
    assert '"error_description": ebay_error_description' in text
