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
