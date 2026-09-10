from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT = ROOT / "services" / "governed_fba_cancellation_safety_alignment.py"
RUNTIME_VISIBILITY = ROOT / "governed_runtime_visibility_routes.py"


def _source(path):
    return path.read_text(encoding="utf-8")


def test_fba_cancellation_safety_fuse_is_installed_without_large_route_rewrite():
    alignment = _source(ALIGNMENT)
    runtime_visibility = _source(RUNTIME_VISIBILITY)

    assert 'SETTING_KEY = "fba_cancel_targeted_refresh_enabled"' in alignment
    assert "install_governed_fba_cancellation_safety_alignment" in runtime_visibility
    assert "@governed_runtime_visibility_bp.record_once" in runtime_visibility


def test_control_is_presented_in_limits_and_safety_not_automation_section():
    source = _source(ALIGNMENT)

    assert 'FBA Cancellation Inventory Refresh' in source
    assert 'data-bt38-safety-control="fba-cancel-targeted-refresh"' in source
    assert '<tr><td>Push Frequency</td>' in source
    assert "SAFETY FUSE:" in source
    assert "full FBA scan" in source
    assert "FBM change" in source


def test_fba_cancellation_uses_exact_persisted_order_skus_only():
    source = _source(ALIGNMENT)

    assert "MarketplaceOrder.marketplace_order_id == order_id" in source
    assert 'getattr(line, "fulfillment_type", None)' in source
    assert 'getattr(line, "sku", None)' in source
    assert "fulfillment not in _FBA_TYPES" in source
    assert '"seller_sku": seller_sku' in source
    assert '"order_id": order_id' in source


def test_existing_runtime_handles_settlement_and_15_minute_verification():
    source = _source(ALIGNMENT)

    assert "notify_governed_runtime_work" in source
    assert "timedelta(seconds=90)" in source
    assert "LIGHT_RECONCILE_SECONDS" in source
    assert 'source="webhook_amazon_cancel_settlement_recheck"' in source
    assert 'source="webhook_amazon_cancel_15m_reconcile"' in source


def test_alignment_never_calculates_or_pushes_fba_quantity():
    source = _source(ALIGNMENT)

    assert '"full_scan_started": False' in source
    assert '"warehouse_mutation_started": False' in source
    assert '"marketplace_push_started": False' in source
    assert '"fbm_changed": False' in source
    assert "available_quantity +" not in source
    assert "reserved_quantity +" not in source
    assert "push_group_listings" not in source
    assert "push_marketplace_listing" not in source


def test_emergency_freeze_turns_new_safety_fuse_off():
    source = _source(ALIGNMENT)

    assert "aligned_emergency_freeze" in source
    assert "_set_config(False)" in source
    assert 'updated[SETTING_KEY] = "false"' in source


def test_existing_automation_controls_are_reported_as_config_not_fake_workers():
    source = _source(ALIGNMENT)

    assert '"ENGINE RUNNING / CONFIG ON"' in source
    assert '"ENGINE RUNNING / CONFIG OFF"' in source
    assert '"GATE OFF"' in source
    assert "CONFIG shows stored permission/configuration" in source
