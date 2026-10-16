"""Static contract tests that do not import BT38 production startup."""
from pathlib import Path


def test_billing_dashboard_is_read_only():
    source = Path("billing_dash_test_routes.py").read_text()
    assert '@billing_dash_test_bp.get("/billing-dash-test")' in source
    assert 'render_template("billing_dash_test.html")' in source
    assert "requests.post" not in source
    assert "db.session" not in source


def test_billing_template_has_test_products_and_no_live_checkout():
    page = Path("templates/billing_dash_test.html").read_text()
    for value in ("£1.00", "£29.00", "£350", "disabled"):
        assert value in page
