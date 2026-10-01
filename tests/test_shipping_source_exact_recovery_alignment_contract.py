from pathlib import Path


SOURCE = Path("services/governed_amazon_exact_order_recovery_route.py")


def test_packlink_shipping_gaps_follow_persisted_shipping_source():
    source = SOURCE.read_text(encoding="utf-8")

    assert 'shipping_source = str(shipment_truth.get("provider")' in source
    assert 'if shipping_source == "packlink" and shipping_gaps:' in source
    assert 'adapter.get_shipment(provider_reference)' in source
    assert 'adapter.get_tracking_status(reference=provider_reference)' in source
    assert 'recover_packlink_provider_spend(shipment, provider_payload)' in source
    assert 'recover_confirmed_packlink_spend(shipment)' in source
    assert 'reconcile_packlink_tracking_lifecycle(' in source


def test_packlink_branch_keeps_amazon_to_marketplace_owned_promises_only():
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index('if shipping_source == "packlink" and shipping_gaps:')
    end = source.index('    calls_started = []', start)
    branch = source[start:end]

    assert 'hydrate_amazon_tracking_for_order(' not in branch
    assert 'hydrate_amazon_purchased_label_for_order(' not in branch
    assert 'if gaps & promise_gaps:' in branch
    assert 'refresh_exact_amazon_order(row)' in branch
    assert '"marketplace_write_started": False' in branch


def test_recover_missing_never_enumerates_beyond_selected_record():
    source = SOURCE.read_text(encoding="utf-8")

    assert "_candidate_order_ids" not in source
    assert "recover_packlink_shipments_for_day" not in source
    assert "find_shipment_by_custom_reference" not in source

    # The DB gate and execution both retain the browser-selected identity.
    assert "before = _database_readback(store_id, order_id)" in source
    assert "MarketplaceOrder.store_id == store_id" in source
    assert "MarketplaceOrder.marketplace_order_id == order_id" in source


def test_packlink_recovery_uses_only_selected_records_persisted_reference():
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index('if shipping_source == "packlink" and shipping_gaps:')
    end = source.index('    calls_started = []', start)
    branch = source[start:end]

    assert 'provider_reference = str(shipment_truth.get("provider_shipment_id")' in branch
    assert "adapter.get_shipment(provider_reference)" in branch
    assert "adapter.get_tracking_status(reference=provider_reference)" in branch
    assert "find_shipment_by_custom_reference" not in branch
    assert "recover_packlink_shipments_for_day" not in branch


def test_committed_refresh_queues_exact_identities_without_dropping_events():
    source = Path("static/js/fbm_tracking_journey.js").read_text(encoding="utf-8")

    assert "const governedLiveRefreshQueue = new Map();" in source
    assert "governedLiveRefreshQueue.set(identity, detail);" in source
    assert "while (governedLiveRefreshQueue.size)" in source
    assert "await applyCommittedFbmSnapshot(detail);" in source
    assert "if (governedLiveRefreshPending) return;\n        const row = committedFbmRow(detail);" not in source
    assert "setInterval(" not in source


def test_targeted_refresh_never_reads_cross_order_price_memory():
    source = Path("services/governed_fbm_page_alignment.py").read_text(encoding="utf-8")

    assert "if missing_spend_rows and not targeted_refresh:" in source
    assert 'request.headers.get("X-BT38-UI-Refresh") == "targeted"' in source
    assert "MarketplaceOrder.marketplace_order_id == targeted_marketplace_order_id" in source
    assert "MarketplaceOrder.store_id == targeted_store_id" in source
