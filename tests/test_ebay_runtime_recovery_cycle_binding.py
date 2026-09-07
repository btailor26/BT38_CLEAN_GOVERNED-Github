from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT = ROOT / "services" / "governed_ebay_runtime_recovery_alignment.py"


def test_ebay_tracking_readback_is_bound_to_full_recovery_cycle():
    source = ALIGNMENT.read_text(encoding="utf-8")

    assert "original_cycle = runtime._run_full_sync_cycle" in source
    assert "def aligned_full_sync_cycle():" in source
    assert "original_cycle()" in source
    assert "_recover_recent_missing_tracking(" in source
    assert "max_days=30" in source
    assert "runtime._run_full_sync_cycle = aligned_full_sync_cycle" in source


def test_alignment_does_not_create_parallel_shipment_or_marketplace_write_path():
    source = ALIGNMENT.read_text(encoding="utf-8")

    assert "FBMShipment(" not in source
    assert "requests.post(" not in source
    assert "requests.put(" not in source
    assert "requests.patch(" not in source
    assert "marketplace_write_started\": False" in source
