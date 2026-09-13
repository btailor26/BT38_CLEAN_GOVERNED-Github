from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT = (ROOT / "services" / "governed_ebay_shipping_label_finance_alignment.py").read_text(encoding="utf-8")
SERVICES_INIT = (ROOT / "services" / "__init__.py").read_text(encoding="utf-8")


def test_exact_ebay_hydration_hooks_finance_only_after_shipment_truth():
    assert "_ORIGINAL_HYDRATE" in ALIGNMENT
    assert 'int(result.get("fulfillment_lifecycle_rows") or 0) > 0' in ALIGNMENT
    assert "read_and_persist_exact_ebay_shipping_label_purchase" in ALIGNMENT
    assert 'result["shipping_label_finance"] = finance_result' in ALIGNMENT


def test_alignment_reuses_existing_exact_hydration_and_adds_no_background_read_path():
    # Contract executable behaviour rather than prose in the module docstring.
    # The wrapper is invoked only by the existing exact-hydration call path and
    # must not introduce its own scheduler/loop/network transport.
    assert "_ORIGINAL_HYDRATE(" in ALIGNMENT
    assert "while True" not in ALIGNMENT
    assert "time.sleep(" not in ALIGNMENT
    assert "schedule." not in ALIGNMENT
    assert "threading." not in ALIGNMENT
    assert "FBMShipment(" not in ALIGNMENT
    assert "requests.get(" not in ALIGNMENT
    assert "requests.post(" not in ALIGNMENT
    assert "governed_ebay_shipping_label_finance_alignment" in SERVICES_INIT
