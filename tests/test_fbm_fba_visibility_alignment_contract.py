from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT = (ROOT / "services" / "governed_fbm_fba_visibility_alignment.py").read_text(encoding="utf-8")
SERVICES_INIT = (ROOT / "services" / "__init__.py").read_text(encoding="utf-8")


def test_fba_visibility_is_installed_without_replacing_fbm_shipping_eligibility():
    assert "import services.governed_fbm_fba_visibility_alignment" in SERVICES_INIT
    assert "dispatch_queue._inject = aligned_inject" in ALIGNMENT
    assert "_workspace_fbm_eligible" not in ALIGNMENT
    assert "shipping_options" not in ALIGNMENT


def test_fba_pending_and_dispatched_have_only_the_requested_local_queues():
    assert 'if status == "pending":\n        return "pending"' in ALIGNMENT
    assert 'return "fba"' in ALIGNMENT
    assert '"shipped"' in ALIGNMENT
    assert '"dispatched"' in ALIGNMENT
    assert '"delivered"' in ALIGNMENT
    assert 'addWorkflowButton(tabBar,\'fba\',\'FBA\');' in ALIGNMENT


def test_fba_rows_are_explicitly_read_only():
    assert 'data-fbm-fba-readonly="1"' in ALIGNMENT
    assert "Fulfilment by Amazon" in ALIGNMENT
    assert ">Read only<" in ALIGNMENT
    assert "fbm-shipping-options" not in ALIGNMENT
    assert "fbm-order-checkbox" not in ALIGNMENT


def test_alignment_reads_db_only_and_does_not_create_inventory_or_marketplace_work():
    assert "MarketplaceOrder" in ALIGNMENT
    assert "joinedload" in ALIGNMENT
    for forbidden in (
        "get_inventory(",
        "get_orders(",
        "requests.get(",
        "requests.post(",
        "notify_governed_runtime_work",
        "AmazonFBAInventory",
        "WarehouseStock",
        "db.session.commit",
        "db.session.add",
        "setattr(",
    ):
        assert forbidden not in ALIGNMENT
