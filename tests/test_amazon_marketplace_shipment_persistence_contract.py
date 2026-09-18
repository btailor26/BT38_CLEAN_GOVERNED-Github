from pathlib import Path


TRACKING = Path(
    "services/governed_amazon_tracking_readback.py"
).read_text(encoding="utf-8")
PROMISE = Path(
    "services/fbm_db_delivery_promise_alignment.py"
).read_text(encoding="utf-8")
LIFECYCLE = Path(
    "services/governed_fbm_lifecycle_alignment.py"
).read_text(encoding="utf-8")
STATE = Path(
    "services/fbm_shipping_state.py"
).read_text(encoding="utf-8")


def test_exact_amazon_package_readback_preserves_physical_shipping_service():
    assert 'package.get("shippingService")' in TRACKING
    assert '"shipping_service": shipment.get("shipping_service")' in TRACKING
    assert "fbm_order_operational_state" in TRACKING
    assert "shipping_service=EXCLUDED.shipping_service" in TRACKING
    assert "IS DISTINCT FROM EXCLUDED.shipping_service" in TRACKING


def test_marketplace_package_service_reuses_existing_fbm_shipment_presentation():
    assert 'provider == "marketplace"' in PROMISE
    assert 'shipment.service = service' in PROMISE
    assert 'item["delivery_promise"] = promise' in PROMISE


def test_marketplace_journey_uses_existing_proxy_without_fake_db_shipment():
    assert 'provider="marketplace"' in LIFECYCLE
    assert "SimpleNamespace(" in LIFECYCLE
    assert "_marketplace_proven_state" in STATE
    assert 'shipment.provider = "marketplace"' in TRACKING
    assert '"marketplace_shipment_persisted": marketplace_shipment_persisted' in TRACKING
    assert '"marketplace_write_started": False' in TRACKING


def test_marketplace_lifecycle_remains_explicit_amazon_truth():
    assert '"PICKEDUPBYCARRIER": "picked_up"' in TRACKING
    assert '"CHECKEDINTOCARRIERHUB": "in_transit"' in TRACKING
    assert '"OUTFORDELIVERY": "out_for_delivery"' in TRACKING
    assert '"DELIVERED": "delivered"' in TRACKING
    assert 'if provider == "marketplace":' in STATE


def test_amazon_package_history_is_persisted_only_to_existing_exact_shipment():
    assert "def _amazon_tracking_events(" in TRACKING
    assert '"trackingEvents", "trackingHistory", "events", "eventHistory"' in TRACKING
    assert "FBMShipmentTrackingEvent(" in TRACKING
    assert 'provider="amazon"' in TRACKING
    assert "raw_event=event" in TRACKING
    assert "event_time=event_time" in TRACKING
    assert "def _ensure_marketplace_shipment(" in TRACKING
    assert 'shipment.provider = "marketplace"' in TRACKING
    assert "shipment.tracking_number = tracking" in TRACKING
    assert '"tracking_events_persisted": tracking_events_persisted' in TRACKING


def test_amazon_history_does_not_promote_observation_time_to_event_time():
    assert "event_time = _parse_iso(event_time_raw)" in TRACKING
    assert "event_time=datetime.utcnow()" not in TRACKING
    assert "observed_at=datetime.utcnow()" in TRACKING
