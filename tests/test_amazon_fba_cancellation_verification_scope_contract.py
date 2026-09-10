from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBHOOK_EXECUTION = ROOT / "services" / "governed_webhook_execution.py"
GOVERNED_ROUTES = ROOT / "governed_routes.py"


def test_fba_cancellation_preserves_exact_inventory_verification_identity():
    source = WEBHOOK_EXECUTION.read_text(encoding="utf-8")

    # Cancellation must carry the exact persisted FBA identity out of the
    # existing MarketplaceOrder rows. It must not infer or calculate stock.
    assert "cancellation_store_id" in source
    assert "cancellation_seller_sku" in source
    assert "cancellation_fulfillment_type" in source
    assert '"store_id": cancellation_store_id' in source
    assert '"seller_sku": cancellation_seller_sku' in source
    assert '"fulfillment_type": cancellation_fulfillment_type' in source
    assert '"fba_inventory_verification_required": cancellation_is_fba' in source


def test_webhook_exact_fba_scope_accepts_cancellation_result_identity():
    source = GOVERNED_ROUTES.read_text(encoding="utf-8")

    # The queue gate must accept fulfillment truth returned by governed
    # execution as well as the raw Amazon summary. This keeps the existing
    # 90-second + 15-minute targeted verification path and creates no new path.
    assert 'notification_result.get("fulfillment_type")' in source
    assert 'notification_result.get("fba_inventory_verification_required")' in source
    assert 'fulfillment_type in {"AFN", "FBA", "AMAZON"}' in source


def test_alignment_does_not_turn_cancellation_into_stock_mutation():
    source = WEBHOOK_EXECUTION.read_text(encoding="utf-8")
    cancellation = source.split("def _handle_marketplace_cancellation", 1)[1]
    cancellation = cancellation.split("def _parse_marketplace_order_timestamp", 1)[0]

    assert '"stock_changed": False' in cancellation
    assert '"correction_started": False' in cancellation
    assert '"push_started": False' in cancellation
