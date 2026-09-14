from pathlib import Path
import ast

SOURCE = Path("services/governed_webhook_execution.py").read_text(encoding="utf-8")


def _function(name: str) -> str:
    tree = ast.parse(SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SOURCE, node) or ""
    raise AssertionError(f"Function not found: {name}")


def test_listing_resolution_does_not_choose_inactive_duplicate_sku():
    fn = _function("_find_listing")
    assert "MarketplaceListing.is_active == True" in fn


def test_amazon_fba_classification_precedes_warehouse_link_guard():
    """Current authority uses the resolved listing fulfillment channel, not stale payload text."""
    fn = _function("process_marketplace_notification")
    fba_classification = fn.index("is_amazon_fba = (")
    warehouse_link = fn.index("stock = listing.warehouse_stock")
    unlinked = fn.index('status="unlinked"')
    assert fba_classification < warehouse_link < unlinked
    assert 'listing_channel not in {"MFN", "FBM", "MERCHANT"}' in fn


def test_afn_fba_order_remains_read_only_inventory_signal():
    """FBA order quantity is never used as Warehouse or FBA inventory authority."""
    fn = _function("process_marketplace_notification")
    assert 'status="fba_order_processed"' in fn
    assert "Order quantity did not mutate Warehouse or FBA inventory" in fn
    assert "Amazon remains FBA inventory authority" in fn
    assert "stock_changed=False" in fn
    assert "push_started=False" in fn


def test_explicit_fba_inventory_truth_uses_amazon_inventory_writer():
    fn = _function("process_marketplace_notification")
    inventory_handoff = fn.index("apply_governed_amazon_fba_event(")
    order_quantity = fn.index("quantity = _extract_quantity(payload)")
    assert inventory_handoff < order_quantity
    assert 'source="amazon_webhook_targeted_fba_handoff"' in fn
