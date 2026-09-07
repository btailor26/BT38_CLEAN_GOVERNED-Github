from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT = ROOT / "services" / "governed_ebay_runtime_recovery_alignment.py"


def test_ebay_tracking_readback_is_bound_to_governed_recovery_function():
    source = ALIGNMENT.read_text(encoding="utf-8")

    assert "original = runtime.run_governed_marketplace_import_refresh" in source
    assert "def aligned_marketplace_import_refresh" in source
    assert 'source != "full_sync_8h_recovery"' in source
    assert "_recover_recent_missing_tracking(" in source
    assert "max_days=30" in source
    assert "runtime.run_governed_marketplace_import_refresh = aligned_marketplace_import_refresh" in source


def test_alignment_does_not_create_parallel_shipment_or_marketplace_write_path():
    source = ALIGNMENT.read_text(encoding="utf-8")

    assert "FBMShipment(" not in source
    assert "requests.post(" not in source
    assert "requests.put(" not in source
    assert "requests.patch(" not in source
    assert "marketplace_write_started\": False" in source
    assert "scheduler_started\": False" in source
    assert "polling_started\": False" in source
