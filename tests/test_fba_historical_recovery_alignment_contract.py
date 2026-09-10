from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
RECOVERY = (ROOT / "services" / "governed_fba_historical_recovery.py").read_text(encoding="utf-8")
RUNNER = (ROOT / "scripts" / "recover_historical_fba_pending.py").read_text(encoding="utf-8")
VISIBILITY = (ROOT / "services" / "governed_fbm_fba_visibility_alignment.py").read_text(encoding="utf-8")


def test_fba_visibility_is_wired_after_dispatch_queue_alignment():
    dispatch = MAIN.index("install_governed_fbm_dispatch_queue_alignment(app)")
    visibility = MAIN.index("import services.governed_fbm_fba_visibility_alignment")
    assert dispatch < visibility
    assert "addWorkflowButton(tabBar,'fba','FBA')" in VISIBILITY
    assert 'if status == "pending":\n        return "pending"' in VISIBILITY
    assert 'if status in _FBA_DISPATCHED:\n        return "fba"' in VISIBILITY


def test_recovery_is_exact_fba_only_and_finite():
    assert 'MarketplaceOrder.marketplace_order_id == order_id' in RECOVERY
    assert '_FBA_TYPES = {"FBA", "AFN"}' in RECOVERY
    assert 'fulfillment_channel != "AFN"' in RECOVERY
    assert 'client.get_order(order_id)' in RECOVERY
    assert 'client.get_order_items(order_id)' in RECOVERY
    assert 'db.func.lower(db.func.coalesce(MarketplaceOrder.status, "")) == "pending"' in RECOVERY
    assert '.limit(max(1, min(int(limit or 500), 2000)))' in RECOVERY


def test_recovery_fills_exact_missing_order_and_promise_truth_only():
    assert 'item.get("SellerSKU")' in RECOVERY
    assert 'item.get("QuantityOrdered")' in RECOVERY
    assert 'item.get("Title")' in RECOVERY
    assert 'order_payload.get("LatestShipDate")' in RECOVERY
    assert 'order_payload.get("EarliestDeliveryDate")' in RECOVERY
    assert 'order_payload.get("LatestDeliveryDate")' in RECOVERY
    assert 'shipping_cost_reason": "not_available_from_orders_api"' in RECOVERY


def test_recovery_never_mutates_stock_or_starts_background_work():
    for token in (
        "process_exact_marketplace_order_line",
        "run_governed_group_propagation",
        "push_stock",
        "while True",
        "threading.Thread",
        "setInterval",
    ):
        assert token not in RECOVERY
    assert '"stock_mutation_started": False' in RECOVERY
    assert '"warehouse_mutation_started": False' in RECOVERY
    assert '"group_propagation_started": False' in RECOVERY
    assert '"marketplace_write_started": False' in RECOVERY
    assert '"polling_started": False' in RECOVERY
    assert '"worker_started": False' in RECOVERY


def test_runner_is_explicit_not_startup_recovery():
    assert 'if __name__ == "__main__":' in RUNNER
    assert "recover_historical_pending_fba" in RUNNER
    assert "recover_historical_fba_pending.py" not in MAIN
