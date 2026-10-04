from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALLBACK = (ROOT / "services" / "fbm_packlink_callback.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "deploy-fly.yml").read_text(encoding="utf-8")
SCRIPT = (ROOT / "scripts" / "recover_packlink_post_deploy.py").read_text(encoding="utf-8")


def test_post_deploy_packlink_selector_is_overdue_undelivered_only():
    section = CALLBACK.split("def recover_packlink_past_delivery_promise", 1)[1].split(
        "def recover_packlink_shipments_for_day", 1
    )[0]
    assert "fs.provider = 'packlink'" in section
    assert "fs.provider_shipment_id IS NOT NULL" in section
    assert "fs.delivered_at IS NULL" in section
    assert "fos.latest_delivery_at IS NOT NULL" in section
    assert "fos.latest_delivery_at < NOW()" in section


def test_post_deploy_packlink_recovery_reads_only_exact_tracking_history():
    section = CALLBACK.split("def recover_packlink_past_delivery_promise", 1)[1].split(
        "def recover_packlink_shipments_for_day", 1
    )[0]
    assert "adapter.get_tracking_status(" in section
    assert "adapter.get_shipment(" not in section
    assert "reconcile_packlink_tracking_lifecycle(" in section
    assert '"marketplace_write_attempted": False' in section
    assert '"polling_started": False' in section


def test_today_no_longer_means_scan_every_packlink_shipment():
    section = CALLBACK.split("def recover_packlink_shipments_for_day", 1)[1]
    assert "recover_packlink_past_delivery_promise(adapter=adapter)" in section
    assert "query.order_by(FBMShipment.id.asc()).all()" not in section
    assert "historical_date_scan_retired_use_exact_manual_recovery" in section


def test_governed_deploy_runs_one_bounded_packlink_recovery():
    assert "Recover overdue Packlink exceptions once" in WORKFLOW
    assert "PYTHONPATH=/app .venv/bin/python -m scripts.recover_packlink_post_deploy" in WORKFLOW
    assert ".venv/bin/python scripts/recover_packlink_post_deploy.py" not in WORKFLOW
    assert "recover_packlink_past_delivery_promise()" in SCRIPT
