from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_amazon_order_change_binds_s02_to_existing_mcf_order_only():
    source = (ROOT / "services" / "governed_mcf_amazon_order_identity_alignment.py").read_text()

    assert 'event_type == "ORDER_CHANGE"' in source
    assert 'text.upper().startswith("MCF-")' in source
    assert 'text.upper().startswith("S02-")' in source
    assert "MCFOrder.seller_fulfillment_order_id.in_(seller_ids)" in source
    assert "mcf.amazon_order_id = incoming" in source


def test_mcf_s02_binding_is_idempotent_and_conflict_safe():
    source = (ROOT / "services" / "governed_mcf_amazon_order_identity_alignment.py").read_text()

    assert 'reason": "amazon_order_id_already_bound"' in source
    assert 'reason": "amazon_order_id_conflict"' in source
    assert 'log_type="mcf_identity_conflict"' in source
    assert "current and current != incoming" in source


def test_mcf_s02_binding_does_not_create_parallel_runtime_paths():
    source = (ROOT / "services" / "governed_mcf_amazon_order_identity_alignment.py").read_text()

    assert "setInterval" not in source
    assert "while True" not in source
    assert "requests." not in source
    assert "create_fulfillment_order" not in source
    assert "MarketplaceOrder(" not in source
