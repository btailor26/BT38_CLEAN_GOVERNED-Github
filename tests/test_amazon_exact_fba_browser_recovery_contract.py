from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE = (ROOT / "services" / "governed_amazon_exact_order_recovery_route.py").read_text(encoding="utf-8")
FBA = (ROOT / "services" / "governed_fba_historical_recovery.py").read_text(encoding="utf-8")


def test_exact_browser_action_routes_existing_fba_to_existing_exact_helper():
    assert '"/governed/actions/amazon/exact-order-recovery"' in ROUTE
    assert '_FBA_TYPES = {"FBA", "AFN"}' in ROUTE
    assert "recover_exact_fba_order(store=store, marketplace_order_id=order_id)" in ROUTE
    assert '"fulfillment_type": "FBA"' in ROUTE
    assert '"broad_scan_started": False' in ROUTE


def test_fba_exact_helper_remains_read_only_outside_order_truth():
    assert "client.get_order(order_id)" in FBA
    assert "client.get_order_items(order_id)" in FBA
    assert '_FBA_TYPES = {"FBA", "AFN"}' in FBA
    assert '"warehouse_mutation_started": False' in FBA
    assert '"group_propagation_started": False' in FBA
    assert '"marketplace_write_started": False' in FBA
    assert '"polling_started": False' in FBA
    assert '"worker_started": False' in FBA


def test_mcf_is_not_routed_to_fba_or_fbm_exact_recovery():
    assert 'not in {"FBA", "AFN", "MCF"}' in ROUTE
    assert '"existing_amazon_order_missing_or_mcf"' in ROUTE
