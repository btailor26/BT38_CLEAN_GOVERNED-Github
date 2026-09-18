from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_recovered_amazon_buy_shipping_uses_existing_spend_authority():
    source = _read("services/governed_amazon_shipping_label_readback.py")

    assert 'service.get("RateWithAdjustments") or service.get("Rate")' in source
    assert "AmazonShippingAdapter._money" in source
    assert "INSERT INTO shipping_spend_ledger" in source
    assert "'amazon_buy_shipping'" in source
    assert "'amazon_buy_shipping_get_shipment_rate'" in source
    assert "ON CONFLICT (dispatch_key) DO UPDATE SET" in source
    assert 'confirmed,\n                recorded_at' in source
    assert "marketplace_write_started\": False" in source


def test_existing_recovered_shipment_can_backfill_missing_cost_without_repurchase():
    source = _read("services/governed_amazon_shipping_label_readback.py")

    existing_start = source.index("# A recovered shipment may pre-date shipping-spend alignment")
    finance_start = source.index("finance = _list_finance_transactions", existing_start)
    existing_path = source[existing_start:finance_start]

    assert "_merchant_shipment(store=store, shipment_id=existing.provider_shipment_id)" in existing_path
    assert "_persist_validated_shipment(" in existing_path
    assert "purchase_shipment(" not in existing_path
    assert "create_shipment" not in existing_path
    assert "requests.post" not in existing_path


def test_amazon_dispatch_event_does_not_skip_missing_confirmed_spend():
    source = _read("services/governed_fbm_shipment_event_alignment.py")

    assert "require_confirmed_spend" in source
    assert "ShippingSpendLedger.query.filter_by(shipment_id=int(shipment.id), confirmed=True)" in source
    assert 'require_confirmed_spend = _text(marketplace).lower() == "amazon"' in source
    assert "purchased_shipment_and_spend_authority_already_persisted" in source
