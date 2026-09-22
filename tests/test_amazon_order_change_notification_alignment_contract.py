from pathlib import Path

EVENTBRIDGE = Path("services/governed_amazon_eventbridge_alignment.py").read_text(encoding="utf-8")
EXECUTION = Path("services/governed_webhook_execution.py").read_text(encoding="utf-8")


def test_existing_eventbridge_route_includes_order_change():
    assert '"ORDER_CHANGE"' in EVENTBRIDGE
    assert '"detail-type": GOVERNED_NOTIFICATION_TYPES' in EVENTBRIDGE
    assert '"new_queue_created": False' in EVENTBRIDGE
    assert '"new_consumer_created": False' in EVENTBRIDGE


def test_cancellation_preserves_existing_marketplace_ship_promise():
    block = EXECUTION.split("def _upsert_fbm_order_operational_state(", 1)[1].split(
        "def _parse_marketplace_order_timestamp(", 1
    )[0]
    assert '"ship_by_at": None' in block
    assert '"ship_by_at": values.get("changed_at")' not in block
    assert "COALESCE(" in block
