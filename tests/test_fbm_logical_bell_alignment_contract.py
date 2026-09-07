from pathlib import Path


SOURCE = Path("services/governed_fbm_logical_bell_alignment.py").read_text(encoding="utf-8")
SERVICES_INIT = Path("services/__init__.py").read_text(encoding="utf-8")


def test_logical_sale_identity_ignores_routine_lifecycle_status():
    block = SOURCE[SOURCE.index("def _sale_identity"):SOURCE.index("def _prefer_sale")]
    assert 'record.get("platform")' in block
    assert 'record.get("order_id")' in block
    assert 'record.get("sku")' in block
    assert 'record.get("quantity")' in block
    assert "lifecycle_status" not in block


def test_historical_pending_unshipped_siblings_choose_stronger_sale_once():
    assert '"pending": 0' in SOURCE
    assert '"unshipped": 1' in SOURCE
    assert "logical_sales[identity]" in SOURCE
    assert "_prefer_sale(existing, record)" in SOURCE


def test_shipment_progress_retires_stale_sale_for_same_order():
    assert "small_alignment._BELL_SHIPMENT_LOG_TYPES" in SOURCE
    assert "progressed_orders" in SOURCE
    assert "if (identity[0], identity[1]) in progressed_orders:" in SOURCE
    assert "continue" in SOURCE


def test_alignment_uses_existing_bell_only_and_stays_passive():
    assert 'endpoint = "governed.governed_ui_notifications"' in SOURCE
    assert "original_install(app)" in SOURCE
    forbidden = (
        "MarketplaceOrder.query",
        "db.session",
        "requests.get",
        "requests.post",
        "setInterval",
        "setTimeout",
        "run_governed_marketplace_import_refresh",
        "hydrate_exact_ebay_order(",
    )
    for term in forbidden:
        assert term not in SOURCE


def test_services_package_installs_logical_bell_before_main_small_alignment_call():
    assert "import services.governed_fbm_logical_bell_alignment" in SERVICES_INIT
    assert "install_governed_fbm_logical_bell_alignment()" in SOURCE
