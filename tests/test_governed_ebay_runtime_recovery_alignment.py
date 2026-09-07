from pathlib import Path


ALIGNMENT = Path("services/governed_ebay_runtime_recovery_alignment.py")
SERVICES_INIT = Path("services/__init__.py")


def test_8h_ebay_recovery_reuses_existing_bounded_tracking_authority():
    source = ALIGNMENT.read_text(encoding="utf-8")

    assert 'source != "full_sync_8h_recovery"' in source
    assert "_recover_recent_missing_tracking(" in source
    assert "max_days=7" in source
    assert "marketplace_write_started" in source
    assert "align_ebay_notifications_and_recover_missed_changes" not in source
    assert "hydrate_exact_ebay_order" not in source


def test_services_startup_installs_ebay_runtime_recovery_alignment():
    source = SERVICES_INIT.read_text(encoding="utf-8")

    assert "import services.governed_ebay_runtime_recovery_alignment" in source
