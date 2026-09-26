from pathlib import Path

SOURCE = Path("services/governed_ebay_shipping_label_readback.py").read_text(encoding="utf-8")


def test_exact_ebay_shipment_truth_does_not_depend_on_finance_proof():
    block = SOURCE[SOURCE.index("def persist_exact_ebay_purchased_shipment_authority("):]
    finance = block.index("purchase = _confirmed_finance_purchase")
    fulfillment = block.index("_fulfillment_truth(")
    assert finance < fulfillment
    assert 'if purchase is None:\n        return' not in block
    assert '"purchase_confirmed": purchase is not None' in block
    assert '"shipping_cost_persisted": purchase is not None' in block


def test_exact_ebay_shipment_truth_persists_governed_order_link():
    block = SOURCE[SOURCE.index("def persist_exact_ebay_purchased_shipment_authority("):]
    assert "INSERT INTO fbm_shipment_order_links" in block
    assert "ON CONFLICT (shipment_id, store_id, marketplace_order_id)" in block
    assert "'ebay_shipping_fulfillment_readback'" in block


def test_unconfirmed_finance_never_invents_shipping_cost():
    block = SOURCE[SOURCE.index("def persist_exact_ebay_purchased_shipment_authority("):]
    assert '"shipping_cost": float(purchase["amount"]) if purchase is not None' in block
    assert '"shipping_cost_currency": str(purchase.get("currency") or "") if purchase is not None else None' in block
    assert '"shipping_cost_records": int(purchase.get("purchase_rows") or 0) if purchase is not None else 0' in block
