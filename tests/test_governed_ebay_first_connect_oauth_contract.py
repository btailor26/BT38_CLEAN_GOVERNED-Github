from pathlib import Path


ROUTES = Path("governed_routes.py").read_text(encoding="utf-8")
STORES = Path("templates/stores.html").read_text(encoding="utf-8")
NOTIFICATIONS = Path("services/governed_ebay_notification_registration.py").read_text(encoding="utf-8")
SCOPES = Path("services/governed_ebay_oauth_scopes.py").read_text(encoding="utf-8")
CONNECT = Path("templates/ebay_oauth.html").read_text(encoding="utf-8")


def test_stores_ui_only_offers_ebay_oauth_when_ebay_is_not_connected():
    assert "{% if not connected.ebay %}" in STORES
    assert "Permission approval required" not in STORES
    assert "Approve eBay" not in STORES
    card = STORES[STORES.index("{% for store in stores %}"):]
    assert 'href="/ebay-oauth/authorize"' not in card
    assert 'href="/ebay-oauth/connect"' not in card


def test_runtime_uses_refresh_token_without_customer_consent_roundtrip():
    assert '"grant_type": "refresh_token"' in SCOPES
    assert "refresh_token" in SCOPES
    assert "/ebay-oauth/authorize" not in SCOPES


def test_notification_capability_does_not_mark_store_for_customer_reauthorization():
    assert '"ebay_reauthorization_required": True' not in NOTIFICATIONS
    assert '"ebay_reauthorization_required": optional_authorization_required' not in NOTIFICATIONS
    assert "seller re-authorization" not in NOTIFICATIONS


def test_first_connect_still_uses_full_governed_scope_authorization():
    assert '@governed_bp.get("/ebay-oauth/authorize")' in ROUTES
    assert '"scope": scopes' in ROUTES
    assert '"grant_type": "authorization_code"' in ROUTES


def test_stores_uses_customer_handoff_before_ebay_authorization():
    assert '@governed_bp.get("/ebay-oauth/connect")' in ROUTES
    assert 'render_template("ebay_oauth.html")' in ROUTES
    assert 'href="/ebay-oauth/connect"' in STORES
    assert 'href="/ebay-oauth/authorize"' not in STORES
    assert 'href="/ebay-oauth/authorize"' in CONNECT
    assert "Continue to eBay" in CONNECT
    assert "manual" not in CONNECT.lower()
