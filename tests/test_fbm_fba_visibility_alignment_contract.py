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


def test_history_fragment_preserves_read_only_fba_visibility():
    source = Path("services/governed_fbm_fba_visibility_alignment.py").read_text(encoding="utf-8")
    assert "original_history_fragment_inject = dispatch_queue._inject_history_fragment_data" in source
    assert "def aligned_history_fragment_inject(html, payload):" in source
    history = source.split("def aligned_history_fragment_inject(html, payload):", 1)[1].split(
        "def aligned_inject(html, payload, _fba_count):", 1
    )[0]
    assert "_insert_rows(html, _canonical_fba_rows())" in history
    assert "next_payload.update(fba_payload)" in history
    assert "original_history_fragment_inject(html, next_payload)" in history
    assert "dispatch_queue._inject_history_fragment_data = aligned_history_fragment_inject" in source
