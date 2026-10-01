from pathlib import Path


def test_buy_shipping_deadline_recovery_is_confirmed_exact_and_one_shot():
    source = Path(
        "services/governed_ebay_buy_shipping_delivery_deadline_alignment.py"
    ).read_text(encoding="utf-8")

    assert "fs.provider = 'ebay_shipping'" in source
    assert "ssl.provider = 'ebay'" in source
    assert "ssl.source = 'ebay_finances_shipping_label'" in source
    assert "ssl.confirmed = TRUE" in source
    assert "fs.delivered_at IS NULL" in source
    assert "os.latest_delivery_at IS NOT NULL" in source
    assert "latest.date() + timedelta(days=1)" in source
    assert "delivery_deadline_already_checked" in source
    assert '"event_type": "ebay_buy_shipping_delivery_deadline"' in source
    assert "LIMIT 250" in source


def test_deadline_event_reuses_exact_ebay_hydration_without_polling():
    runtime = Path("services/governed_runtime_engine.py").read_text(encoding="utf-8")
    alignment = Path(
        "services/governed_ebay_buy_shipping_delivery_deadline_alignment.py"
    ).read_text(encoding="utf-8")

    assert 'event_type == "ebay_buy_shipping_delivery_deadline"' in runtime
    assert "hydrate_exact_ebay_order(" in runtime
    assert "confirmed_ebay_buy_shipping" in alignment
    assert "poll" not in alignment.lower().replace("poller", "")


def test_shipment_commit_publishes_canonical_marketplace_order_refresh_identity():
    source = Path("services/governed_exact_record_event_alignment.py").read_text(encoding="utf-8")
    browser = Path("static/js/fbm_tracking_journey.js").read_text(encoding="utf-8")

    assert 'scope["marketplace_order_id"] = marketplace_order_id' in source
    assert 'scope["store_id"] = _value(row, "store_id")' in source
    assert "committedRefreshIdentity(detail)" in browser
    assert "detail?.marketplace_order_id" in browser
    assert "applyCommittedFbmSnapshot(detail)" in browser
    assert "openPersistedJourney(currentTrackingButton)" in browser
