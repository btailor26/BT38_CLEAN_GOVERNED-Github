from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QZ_SOURCE = ROOT / "static" / "js" / "fbm_qz_print.js"
GUNICORN_SOURCE = ROOT / "gunicorn.conf.py"


def test_bulk_shipping_options_are_not_aborted_by_the_browser_15_second_guard():
    source = QZ_SOURCE.read_text(encoding="utf-8")

    assert "const FBM_FETCH_TIMEOUT_MS = 15000" in source
    assert "parsed.pathname === '/fbm/shipping-options'" in source
    assert "isBulkShippingOptions = orderIds.length > 1" in source
    assert "!isFbmRequest || isBulkShippingOptions || init.signal" in source


def test_single_fbm_requests_keep_the_existing_timeout_guard():
    source = QZ_SOURCE.read_text(encoding="utf-8")

    assert "controller.abort()" in source
    assert "Shipping request timed out after 15 seconds" in source


def test_server_keeps_a_bounded_ceiling_for_explicit_marketplace_operations():
    source = GUNICORN_SOURCE.read_text(encoding="utf-8")

    assert "timeout = 600" in source
