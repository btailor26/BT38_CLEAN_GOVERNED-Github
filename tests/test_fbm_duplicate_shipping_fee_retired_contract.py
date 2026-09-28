from pathlib import Path


DISPATCH = Path("services/governed_fbm_dispatch_queue_alignment.py").read_text(encoding="utf-8")


def test_dispatch_overlay_never_creates_duplicate_shipping_fee_column():
    assert "ensureFeesHeader" not in DISPATCH
    assert "addCostCell" not in DISPATCH
    assert "data-fbm-shipping-fees" not in DISPATCH
    assert "th.textContent='Shipping Fee'" not in DISPATCH
    assert "alignCanonicalShippingCost" in DISPATCH
    assert "row.querySelector('.fbm-shipping-cost-cell')" in DISPATCH


def test_dispatch_overlay_uses_persisted_cost_truth():
    assert "row.mcf_order.total_mcf_fee" in DISPATCH
    assert "float(spend.amount)" in DISPATCH
    assert "row.mcf_order.mcf_fulfillment_fee" not in DISPATCH
