"""Billing test checkout contract: isolated route and no BT38 data writes."""
from pathlib import Path


def test_billing_dashboard_checkout_contract():
    source = Path("billing_dash_test_routes.py").read_text()
    assert '@billing_dash_test_bp.get("/billing-dash-test")' in source
    assert '@billing_dash_test_bp.post("/billing-dash-test/checkout")' in source
    assert 'render_template("billing_dash_test.html"' in source
    assert '"amount": 100' in source
    assert '"currency": "GBP"' in source
    assert 'checkout_url' in source
    assert "db.session" not in source
    assert "credits.grant" not in source


def test_billing_template_has_active_test_checkout():
    page = Path("templates/billing_dash_test.html").read_text()
    assert 'action="/billing-dash-test/checkout"' in page
    assert 'type="submit"' in page
    assert "Pay £1 with Revolut" in page
    assert "£29.00" in page
    assert "£350" in page
