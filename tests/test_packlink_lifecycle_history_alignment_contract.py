from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALLBACK = (ROOT / "services" / "fbm_packlink_callback.py").read_text(encoding="utf-8")
POST_PURCHASE = (ROOT / "services" / "fbm_post_purchase.py").read_text(encoding="utf-8")


def test_tracking_history_can_promote_terminal_delivery_truth():
    assert "def _canonical_tracking_lifecycle" in CALLBACK
    assert 'return "DELIVERED"' in CALLBACK
    assert 'return "IN_TRANSIT"' in CALLBACK
    assert 'return "ACCEPTED"' in CALLBACK
    assert "tracking_history" in CALLBACK
    assert "reconcile_provider_lifecycle_state" in CALLBACK


def test_current_packlink_state_beats_stale_terminal_history():
    assert "def _provider_state_lifecycle" in CALLBACK
    lifecycle = CALLBACK.split("def reconcile_packlink_tracking_lifecycle", 1)[1].split("def _first_label_url", 1)[0]
    assert "current = _provider_state_lifecycle(provider_state)" in lifecycle
    assert "current or _canonical_tracking_lifecycle(None, tracking_history)" in lifecycle
    assert 'shipment.delivered_at = None' in lifecycle
    assert 'shipment.status = "in_transit"' in lifecycle


def test_confirmed_historical_packlink_rows_refresh_lifecycle_without_marketplace_write():
    assert "marketplace_confirmed_at is not None" in CALLBACK
    assert '"lifecycle_only": True' in CALLBACK
    assert '"marketplace_write_attempted": False' in CALLBACK
    recovery = CALLBACK.split("def recover_packlink_shipments_for_day", 1)[1]
    assert "FBMShipment.marketplace_confirmed_at.is_(None)" not in recovery


def test_previously_known_packlink_rows_get_one_shot_lifecycle_recovery_only():
    recovery = CALLBACK.split("def recover_packlink_shipments_for_day", 1)[1]
    assert "historical_cutoff = start - timedelta(days=6)" in recovery
    assert "historical_lifecycle_only" in recovery
    assert '"historical_recovery": historical_lifecycle_only' in recovery
    assert "historical_lifecycle_only or shipment.marketplace_confirmed_at is not None" in recovery


def test_shared_journey_remains_timestamp_authority():
    assert "shipment.delivered_at = shipment.delivered_at or observed_at" in POST_PURCHASE
    assert "shipment.first_movement_at = shipment.first_movement_at or observed_at" in POST_PURCHASE
    assert "shipment.carrier_accepted_at = shipment.carrier_accepted_at or observed_at" in POST_PURCHASE


def test_no_created_at_cutoff_is_added_to_lifecycle_classification():
    lifecycle = CALLBACK.split("def _canonical_tracking_lifecycle", 1)[1].split("def _first_label_url", 1)[0]
    assert "created_at" not in lifecycle


def test_packlink_history_is_persisted_without_an_extra_provider_call():
    lifecycle = CALLBACK.split("def reconcile_packlink_tracking_lifecycle", 1)[1].split("def _first_label_url", 1)[0]
    assert "_persist_packlink_tracking_history(" in lifecycle
    assert "adapter." not in lifecycle
    assert "requests." not in lifecycle


def test_carrier_event_time_is_separate_from_bt38_observation_time():
    assert "def _tracking_event_time" in CALLBACK
    lifecycle = CALLBACK.split("def reconcile_packlink_tracking_lifecycle", 1)[1].split("def _first_label_url", 1)[0]
    assert 'shipment.carrier_accepted_at = accepted_at' in lifecycle
    assert 'shipment.first_movement_at = movement_at' in lifecycle
    assert 'shipment.delivered_at = delivered_at' in lifecycle
    assert "shipment.last_provider_checked_at = checked_at" in lifecycle


def test_packlink_history_uses_existing_tracking_event_ledger():
    assert "FBMShipmentTrackingEvent" in CALLBACK
    persist = CALLBACK.split("def _persist_packlink_tracking_history", 1)[1].split("def _milestone_event_time", 1)[0]
    assert 'provider="packlink"' in persist
    assert "raw_event = item" in persist
    assert "event_time = event_time" in persist
    assert "observed_at = observed_at" in persist
