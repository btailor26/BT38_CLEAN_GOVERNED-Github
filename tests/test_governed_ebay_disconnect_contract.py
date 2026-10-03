from pathlib import Path


SOURCE = Path("services/governed_marketplace_disconnect.py").read_text(encoding="utf-8")


def test_ebay_disconnect_prefers_persisted_refresh_token_authority():
    assert 'refresh_token = str(credentials.get("refresh_token")' in SOURCE
    assert 'token = refresh_token or access_token' in SOURCE
    assert '"refresh_token" if refresh_token else "access_token"' in SOURCE


def test_ebay_disconnect_uses_production_oauth_revocation_endpoint():
    assert '"https://api.ebay.com/identity/v1/oauth2/token/revoke"' in SOURCE
    assert '"Authorization": f"Basic {basic}"' in SOURCE
    assert '"token": token' in SOURCE
    assert '"token_type_hint": token_type_hint' in SOURCE


def test_ebay_disconnect_never_exposes_persisted_token_in_result():
    result_section = SOURCE[SOURCE.index("if response.status_code >= 300:"):]
    assert '"token": token' not in result_section
    assert '"refresh_token": refresh_token' not in result_section
